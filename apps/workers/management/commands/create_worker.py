from django.core.management.base import BaseCommand
from apps.accounts.models import Account
from apps.workers.models import Worker


class Command(BaseCommand):
    help = 'Create worker user (Account + Worker profile)'
    
    def add_arguments(self, parser):
        parser.add_argument('--email', type=str, default='worker@neatnow.com')
        parser.add_argument('--password', type=str, default='Worker@123')
        parser.add_argument('--name', type=str, default='Test Worker')
        parser.add_argument('--phone', type=str, default='', required=False)
        parser.add_argument('--employee-code', type=str, default='WRK001')
    
    def handle(self, *args, **options):
        email = options['email'].lower().strip()
        password = options['password']
        name = options['name']
        phone = options.get('phone', '')
        employee_code = options['employee_code']
        
        # Check if account already exists
        if Account.objects.filter(email=email).exists():
            account = Account.objects.get(email=email)
            self.stdout.write(self.style.WARNING(f'❌ Account with email {email} already exists!'))
            self.stdout.write(f'Account ID: {account.account_id}')
            self.stdout.write(f'Name: {account.name}')
            self.stdout.write(f'Role: {account.role}')
            
            # Check if worker profile exists
            if hasattr(account, 'worker_profile'):
                worker = account.worker_profile
                self.stdout.write(f'Worker Employee Code: {worker.employee_code}')
            else:
                self.stdout.write('⚠️  Account exists but no worker profile found.')
                self.stdout.write('To create worker profile, run:')
                self.stdout.write(f'  Worker.objects.create(worker_id=account, employee_code="{employee_code}")')
            return
        
        # Check if employee code already exists
        if Worker.objects.filter(employee_code=employee_code).exists():
            self.stdout.write(self.style.ERROR(f'❌ Employee code {employee_code} already exists!'))
            return
        
        try:
            # Create Account
            account = Account.objects.create_user(
                email=email,
                password=password,
                name=name,
                phone_number=phone,
                role='Worker',
                is_active=True
            )
            
            # Create Worker profile
            worker = Worker.objects.create(
                worker_id=account,
                employee_code=employee_code
            )
            
            self.stdout.write(self.style.SUCCESS('✅ Worker created successfully!'))
            self.stdout.write('=' * 50)
            self.stdout.write(f'Email: {email}')
            self.stdout.write(f'Password: {password}')
            self.stdout.write(f'Name: {name}')
            self.stdout.write(f'Phone: {phone if phone else "Not provided"}')
            self.stdout.write(f'Employee Code: {employee_code}')
            self.stdout.write(f'Account ID: {account.account_id}')
            self.stdout.write(f'Worker ID: {worker.worker_id.account_id}')
            self.stdout.write('=' * 50)
            self.stdout.write(self.style.SUCCESS('✅ Use these credentials in Flutter app for worker login'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ Error creating worker: {str(e)}'))

