from django.core.mail import send_mail
from django.conf import settings
from django.utils.html import strip_tags


class EmailService:
    
    @staticmethod
    def send_password_reset(to_email, name, reset_link):
        subject = 'Password Reset Request - Waste Management System'
        html_message = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #333;">Hello {name},</h2>
                <p>You requested to reset your password for the Waste Management Admin Portal.</p>
                <p>Click the button below to reset your password:</p>
                <a href="{reset_link}" 
                   style="display: inline-block; background-color: #4CAF50; color: white; 
                          padding: 12px 24px; text-decoration:  none; border-radius: 5px; 
                          margin:  15px 0;">
                    Reset Password
                </a>
                <p style="color: #666; font-size: 14px;">
                    This link will expire in 1 hour.
                </p>
                <p style="color: #999; font-size: 12px;">
                    If you didn't request this, please ignore this email.
                </p>
                <hr style="margin: 20px 0; border: none; border-top: 1px solid #eee;">
                <p style="color: #666;">
                    Best regards,<br>
                    <strong>Waste Management Team</strong>
                </p>
            </body>
        </html>
        """
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            html_message=html_message,
            fail_silently=False,
        )
    
    @staticmethod
    def send_password_changed_notification(to_email, name):
        subject = 'Password Changed Successfully'
        html_message = f"""
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #333;">Hello {name},</h2>
                <p>Your password has been changed successfully.</p>
                <p style="color: #d32f2f; font-weight: bold;">
                    If you did not make this change, please contact support immediately. 
                </p>
                <hr style="margin: 20px 0; border: none; border-top: 1px solid #eee;">
                <p style="color: #666;">
                    Best regards,<br>
                    <strong>Waste Management Team</strong>
                </p>
            </body>
        </html>
        """
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            html_message=html_message,
            fail_silently=False,
        )
    
    @staticmethod
    def send_login_link(to_email, user_type, login_link):
        subject = f'Login to Waste Management {user_type. title()} App'
        html_message = f"""
        <html>
            <body style="font-family:  Arial, sans-serif; padding:  20px;">
                <h2 style="color: #333;">Welcome to Waste Management System! </h2>
                <p>You have been invited to access the <strong>{user_type}</strong> mobile application.</p>
                <p>Click the button below to login:</p>
                <a href="{login_link}" 
                   style="display: inline-block; background-color: #2196F3; color: white; 
                          padding: 12px 24px; text-decoration: none; border-radius: 5px; 
                          margin: 15px 0;">
                    Login Now
                </a>
                <hr style="margin: 20px 0; border: none; border-top: 1px solid #eee;">
                <p style="color: #666;">
                    Best regards,<br>
                    <strong>Waste Management Team</strong>
                </p>
            </body>
        </html>
        """
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [to_email],
            html_message=html_message,
            fail_silently=False,
        )