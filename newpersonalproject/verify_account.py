from app import app, db
from models import User

def verify_user(email):
    with app.app_context():
        user = User.query.filter_by(email=email).first()
        if not user:
            print(f"No user found with email: {email}")
            return
        
        if user.is_verified:
            print("User is already verified")
            return
        
        # Directly verify the user
        user.is_verified = True
        db.session.commit()
        print(f"User {email} has been verified successfully!")

if __name__ == "__main__":
    email = "alickmasihjames@gmail.com"  # Replace with your email
    verify_user(email) 