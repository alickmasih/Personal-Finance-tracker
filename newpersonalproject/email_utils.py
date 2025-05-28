from flask_mail import Message
from flask import render_template, current_app
from extensions import mail
from threading import Thread

def send_async_email(app, msg):
    """Send email asynchronously"""
    with app.app_context():
        mail.send(msg)

def send_email(subject, recipients, template, **kwargs):
    """
    Send email using template
    
    Args:
        subject: Email subject
        recipients: List of recipient email addresses
        template: Template name without extension
        **kwargs: Template variables
    """
    app = current_app._get_current_object()
    msg = Message(
        subject=subject,
        recipients=recipients,
        sender=app.config['MAIL_DEFAULT_SENDER']
    )
    
    # Render both HTML and text versions
    msg.html = render_template(f'emails/{template}.html', **kwargs)
    msg.body = render_template(f'emails/{template}.txt', **kwargs)
    
    # Send email asynchronously
    Thread(target=send_async_email, args=(app, msg)).start()

def send_verification_email(user, verification_url):
    """Send email verification link to user"""
    send_email(
        subject='Verify Your Email - Personal Finance Tracker',
        recipients=[user.email],
        template='verify_email',
        user=user,
        verification_url=verification_url
    ) 