from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
import uuid


class AdminManager(BaseUserManager):
    """Custom manager for Admin model"""
    
    def create_admin(self, email, password, name):
        if not email:
            raise ValueError('Admin must have an email address')
        
        if not password:
            raise ValueError('Admin must have a password')
        
        admin = self.model(
            email=self.normalize_email(email),
            name=name
        )
        admin.set_password(password)
        admin.save(using=self._db)
        return admin


class Admin(AbstractBaseUser):
    """
    Admin model for management dashboard
    Separate from Django's default User model for security
    """
    admin_id = models.AutoField(primary_key=True)
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    password_hash = models.CharField(max_length=255)
    name = models.CharField(max_length=150)
    created_at = models.DateTimeField(default=timezone.now)
    
    # Password reset functionality
    reset_token = models.CharField(max_length=100, null=True, blank=True)
    reset_token_expires = models.DateTimeField(null=True, blank=True)
    
    # Session management
    last_login = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    # Additional fields
   
    
    # Permissions
    role = models.CharField(
        max_length=50,
        default='admin',
        choices=[
            ('admin', 'Admin'),
            ('super_admin', 'Super Admin'),
            ('moderator', 'Moderator'),
        ]
    )
    
    objects = AdminManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    
    # Override password field (we use password_hash instead)
    password = None
    
    class Meta:
        db_table = 'admins'
        verbose_name = 'Admin'
        verbose_name_plural = 'Admins'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.name} ({self.email})"
    
    def set_password(self, raw_password):
        """Hash and set password"""
        self.password_hash = make_password(raw_password)
    
    def check_password(self, raw_password):
        """Verify password"""
        return check_password(raw_password, self. password_hash)
    
    def generate_reset_token(self):
        """Generate password reset token"""
        self.reset_token = str(uuid.uuid4())
        self.reset_token_expires = timezone. now() + timezone.timedelta(hours=24)
        self.save()
        return self. reset_token
    
    def verify_reset_token(self, token):
        """Verify if reset token is valid"""
        if not self.reset_token or not self.reset_token_expires:
            return False
        
        if self.reset_token != token:
            return False
        
        if timezone.now() > self.reset_token_expires:
            return False
        
        return True
    
    def clear_reset_token(self):
        """Clear password reset token"""
        self.reset_token = None
        self.reset_token_expires = None
        self.save()
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = timezone.now()
        self.save(update_fields=['last_login'])