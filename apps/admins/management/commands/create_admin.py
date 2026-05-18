from django.core.management.base import BaseCommand
from apps.admins.models import Admin


class Command(BaseCommand):
    help = 'Create admin user'
    
    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, default='admin@cleanup.gov')
        parser.add_argument('--password', type=str, default='Admin@123456')
        parser.add_argument('--name', type=str, default='Super Admin')
        parser.add_argument('--role', type=str, default='super_admin')
    
    def handle(self, *args, **options):
        email = options['email']
        password = options['password']
        name = options['name']
        role = options['role']
        
        if Admin.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f'❌ Admin {email} already exists! '))
            admin = Admin.objects.get(email=email)
            self.stdout.write(f'Admin ID: {admin.admin_id}')
            self.stdout.write(f'Name: {admin.name}')
            self.stdout.write(f'Role: {admin.role}')
            return
        
        admin = Admin.objects.create(
            email=email,
            name=name,
            role=role
        )
        admin.set_password(password)
        admin.save()
        
        self.stdout.write(self.style.SUCCESS(f'✅ Admin created successfully!'))
        self.stdout.write(f'Email: {email}')
        self.stdout.write(f'Password: {password}')
        self.stdout.write(f'Name: {name}')
        self.stdout.write(f'Role: {role}')
        self.stdout.write(f'Admin ID: {admin.admin_id}')