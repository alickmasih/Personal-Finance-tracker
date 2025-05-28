from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import func
from flask_migrate import Migrate
import os

from extensions import db, login_manager, mail
from models import User, Transaction, UserActivity, Analytics
from expense_categorizer import categorize_expense_nlp
from expense_forecaster import ExpenseForecaster
from email_utils import send_verification_email

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///finance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_LOGIN_ATTEMPTS'] = 5
app.config['ACCOUNT_LOCKOUT_MINUTES'] = 30

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@personalfinance.com')

# Initialize extensions
db.init_app(app)
login_manager.init_app(app)
mail.init_app(app)
migrate = Migrate(app, db)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied. Admin privileges required.')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def log_activity(user_id, activity_type, description, is_suspicious=False):
    activity = UserActivity(
        user_id=user_id,
        activity_type=activity_type,
        description=description,
        ip_address=request.remote_addr,
        is_suspicious=is_suspicious
    )
    db.session.add(activity)
    db.session.commit()

def update_daily_analytics():
    today = datetime.now().date()
    analytics = Analytics.query.filter_by(date=today).first()
    
    if not analytics:
        analytics = Analytics(date=today)
        db.session.add(analytics)
    
    # Update analytics
    analytics.total_users = User.query.count()
    analytics.active_users = UserActivity.query.filter(
        func.date(UserActivity.timestamp) == today
    ).distinct(UserActivity.user_id).count()
    
    today_transactions = Transaction.query.filter(
        func.date(Transaction.date) == today
    ).all()
    
    analytics.total_transactions = len(today_transactions)
    analytics.total_income = sum(t.amount for t in today_transactions if t.type == 'income')
    analytics.total_expense = sum(t.amount for t in today_transactions if t.type == 'expense')
    
    if today_transactions:
        analytics.avg_transaction_amount = sum(t.amount for t in today_transactions) / len(today_transactions)
        
        # Find most common category
        category_counts = {}
        for t in today_transactions:
            category_counts[t.category] = category_counts.get(t.category, 0) + 1
        if category_counts:
            analytics.most_common_category = max(category_counts.items(), key=lambda x: x[1])[0]
    
    db.session.commit()

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    # Get overall statistics
    total_users = User.query.count()
    total_transactions = Transaction.query.count()
    
    # Get recent activities
    recent_activities = UserActivity.query.order_by(UserActivity.timestamp.desc()).limit(10).all()
    
    # Get suspicious activities
    suspicious_activities = UserActivity.query.filter_by(is_suspicious=True)\
        .order_by(UserActivity.timestamp.desc()).limit(5).all()
    
    # Get user statistics
    user_stats = db.session.query(
        User.id,
        User.email,
        func.count(Transaction.id).label('transaction_count'),
        func.sum(Transaction.amount).label('total_amount')
    ).join(Transaction).group_by(User.id).all()
    
    # Get popular categories
    category_stats = db.session.query(
        Transaction.category,
        func.count(Transaction.id).label('count'),
        func.sum(Transaction.amount).label('total_amount')
    ).group_by(Transaction.category).all()
    
    # Get analytics trend
    analytics_trend = Analytics.query.order_by(Analytics.date.desc()).limit(7).all()
    
    return render_template('admin/dashboard.html',
                         total_users=total_users,
                         total_transactions=total_transactions,
                         recent_activities=recent_activities,
                         suspicious_activities=suspicious_activities,
                         user_stats=user_stats,
                         category_stats=category_stats,
                         analytics_trend=analytics_trend)

@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users = User.query.all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/analytics')
@login_required
@admin_required
def admin_analytics():
    # Get date range
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    
    analytics = Analytics.query.filter(
        Analytics.date.between(start_date, end_date)
    ).order_by(Analytics.date.asc()).all()
    
    return render_template('admin/analytics.html', analytics=analytics)

@app.route('/admin/activity-log')
@login_required
@admin_required
def admin_activity_log():
    activities = UserActivity.query.order_by(UserActivity.timestamp.desc()).all()
    return render_template('admin/activity_log.html', activities=activities)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def get_date_range(range_type):
    today = datetime.now().date()
    
    if range_type == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=6)
    elif range_type == 'month':
        start_date = today.replace(day=1)
        # Get last day of current month
        if today.month == 12:
            end_date = today.replace(day=31)
        else:
            end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    elif range_type == 'year':
        start_date = today.replace(month=1, day=1)
        end_date = today.replace(month=12, day=31)
    elif range_type == 'all':
        return None, None
    else:  # Custom range or invalid type
        try:
            start_date = datetime.strptime(request.args.get('start_date', ''), '%Y-%m-%d').date()
            end_date = datetime.strptime(request.args.get('end_date', ''), '%Y-%m-%d').date()
        except ValueError:
            start_date = today - timedelta(days=30)  # Default to last 30 days
            end_date = today
    
    return start_date, end_date

def get_filtered_data(start_date=None, end_date=None):
    # Base query
    query = Transaction.query.filter_by(user_id=current_user.id)
    
    # Apply date filtering if dates are specified
    if start_date and end_date:
        query = query.filter(Transaction.date >= start_date, Transaction.date <= end_date)
    
    # Get transactions and sort by date
    transactions = query.order_by(Transaction.date.desc()).all()
    
    # Calculate summary statistics
    total_income = sum(t.amount for t in transactions if t.type == 'income')
    total_expense = sum(t.amount for t in transactions if t.type == 'expense')
    savings = total_income - total_expense
    
    # Category-wise spending
    categories = {}
    for t in transactions:
        if t.type == 'expense':
            categories[t.category] = categories.get(t.category, 0) + t.amount
    
    # Get monthly data for trend chart
    monthly_data = {}
    for transaction in transactions:
        month_key = transaction.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {'income': 0, 'expense': 0}
        monthly_data[month_key][transaction.type] += transaction.amount
    
    # Sort months chronologically
    sorted_months = sorted(monthly_data.keys())
    trend_data = {
        'labels': [datetime.strptime(m, '%Y-%m').strftime('%b %Y') for m in sorted_months],
        'income': [monthly_data[m]['income'] for m in sorted_months],
        'expense': [monthly_data[m]['expense'] for m in sorted_months]
    }
    
    return {
        'summary': {
            'total_income': total_income,
            'total_expense': total_expense,
            'savings': savings
        },
        'categories': categories,
        'trend_data': trend_data,
        'transactions': [{
            'date': t.date.strftime('%Y-%m-%d'),
            'type': t.type,
            'category': t.category,
            'amount': t.amount,
            'note': t.note,
            'id': t.id
        } for t in transactions]
    }

@app.route('/api/dashboard-data')
@login_required
def get_dashboard_data():
    date_range = request.args.get('range', 'month')
    start_date, end_date = get_date_range(date_range)
    return jsonify(get_filtered_data(start_date, end_date))

@app.route('/')
@login_required
def dashboard():
    date_range = request.args.get('range', 'month')
    start_date, end_date = get_date_range(date_range)
    data = get_filtered_data(start_date, end_date)
    
    return render_template('dashboard.html',
                         transactions=data['transactions'],
                         total_income=data['summary']['total_income'],
                         total_expense=data['summary']['total_expense'],
                         savings=data['summary']['savings'],
                         categories=data['categories'],
                         trend_data=data['trend_data'],
                         current_range=date_range,
                         start_date=start_date,
                         end_date=end_date)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user:
            if not user.is_verified:
                flash('Please verify your email before logging in.')
                return redirect(url_for('login'))
                
            if user.is_locked:
                lockout_time = datetime.utcnow() - timedelta(minutes=app.config['ACCOUNT_LOCKOUT_MINUTES'])
                if user.last_login and user.last_login < lockout_time:
                    # Reset lockout
                    user.is_locked = False
                    user.failed_login_attempts = 0
                else:
                    flash('Account is locked. Please try again later.')
                    return redirect(url_for('login'))
            
            if check_password_hash(user.password_hash, password):
                login_user(user)
                user.last_login = datetime.utcnow()
                user.failed_login_attempts = 0
                db.session.commit()
                
                log_activity(user.id, 'login', 'Successful login')
                return redirect(url_for('dashboard'))
            else:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= app.config['MAX_LOGIN_ATTEMPTS']:
                    user.is_locked = True
                    log_activity(user.id, 'login_failed', 
                               'Account locked due to multiple failed attempts',
                               is_suspicious=True)
                else:
                    log_activity(user.id, 'login_failed', 
                               f'Failed login attempt ({user.failed_login_attempts})',
                               is_suspicious=user.failed_login_attempts >= 3)
                db.session.commit()
                
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists')
            return redirect(url_for('register'))
        
        user = User(
            name=name, 
            email=email, 
            password_hash=generate_password_hash(password),
            verification_sent_at=datetime.utcnow()
        )
        db.session.add(user)
        db.session.commit()
        
        # Generate verification token and URL
        token = user.get_verification_token()
        verification_url = url_for('verify_email', token=token, _external=True)
        
        # Send verification email
        send_verification_email(user, verification_url)
        
        flash('Registration successful! Please check your email to verify your account.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    email = User.verify_token(token)
    if not email:
        flash('The verification link is invalid or has expired.')
        return redirect(url_for('login'))
    
    user = User.query.filter_by(email=email).first()
    if not user:
        flash('User not found.')
        return redirect(url_for('login'))
    
    if user.is_verified:
        flash('Email already verified. Please login.')
        return redirect(url_for('login'))
    
    user.is_verified = True
    db.session.commit()
    
    flash('Your email has been verified! You can now login.')
    return redirect(url_for('login'))

@app.route('/resend-verification')
@login_required
def resend_verification():
    if current_user.is_verified:
        flash('Your email is already verified.')
        return redirect(url_for('dashboard'))
    
    # Check if we should allow resending (prevent spam)
    if current_user.verification_sent_at:
        time_since_last = datetime.utcnow() - current_user.verification_sent_at
        if time_since_last < timedelta(minutes=5):
            flash('Please wait 5 minutes before requesting another verification email.')
            return redirect(url_for('dashboard'))
    
    # Generate new verification token and URL
    token = current_user.get_verification_token()
    verification_url = url_for('verify_email', token=token, _external=True)
    
    # Update verification sent timestamp
    current_user.verification_sent_at = datetime.utcnow()
    db.session.commit()
    
    # Send new verification email
    send_verification_email(current_user, verification_url)
    
    flash('A new verification email has been sent. Please check your inbox.')
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    amount = float(request.form.get('amount'))
    type = request.form.get('type')
    category = request.form.get('category')
    note = request.form.get('note')
    date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
    
    # Auto-categorize if no category is provided
    if not category and note:
        category = categorize_expense_nlp(note)
    
    transaction = Transaction(
        amount=amount,
        type=type,
        category=category,
        note=note,
        date=date,
        user_id=current_user.id
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    log_activity(current_user.id, 'transaction_add', 
                f'Added {type} transaction: {amount} in {category}')
    update_daily_analytics()
    
    flash('Transaction added successfully!')
    return redirect(url_for('dashboard'))

@app.route('/delete_transaction/<int:id>')
@login_required
def delete_transaction(id):
    transaction = Transaction.query.get_or_404(id)
    if transaction.user_id != current_user.id:
        flash('Unauthorized access!')
        return redirect(url_for('dashboard'))
    
    db.session.delete(transaction)
    db.session.commit()
    flash('Transaction deleted successfully!')
    return redirect(url_for('dashboard'))

@app.route('/api/forecast')
@login_required
def get_expense_forecast():
    # Get period from query parameters (default to 12 months)
    period = request.args.get('period', '12')
    try:
        period = int(period)
    except ValueError:
        period = 12

    # Get user's transaction history with period filter
    query = Transaction.query.filter_by(user_id=current_user.id)
    
    if period > 0:  # If period is 0, get all data
        cutoff_date = datetime.now().date() - timedelta(days=period * 30)  # Approximate months
        query = query.filter(Transaction.date >= cutoff_date)
    
    transactions = query.order_by(Transaction.date.asc()).all()
    
    # Initialize forecaster
    forecaster = ExpenseForecaster()
    
    # Get predictions
    next_month_prediction = forecaster.predict_next_month(transactions)
    category_predictions = forecaster.get_category_predictions(transactions)
    
    return jsonify({
        'total_prediction': next_month_prediction,
        'category_predictions': category_predictions
    })

@app.route('/forecast')
@login_required
def forecast_dashboard():
    return render_template('forecast.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True) 