from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User
from accounts.forms import SignUpForm, AdminUserCreationForm, AdminUserUpdateForm


class EduEmailConstraintFormTests(TestCase):
    """
    Unit tests verifying that SignUpForm, AdminUserCreationForm, and AdminUserUpdateForm
    enforce the educational email constraint (.edu or .edu.bd) for Student, Instructor,
    and Course Coordinator roles, while exempting Admin.
    """

    def test_signup_form_rejects_non_edu_email_for_student(self):
        form_data = {
            'name': 'John Student',
            'email': 'student@gmail.com',
            'role': User.Role.STUDENT,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn(
            "A valid university email (.edu or .edu.bd) is required for this role.",
            form.errors['email']
        )

    def test_signup_form_accepts_edu_email_for_student(self):
        form_data = {
            'name': 'John Student',
            'email': 'student@university.edu',
            'role': User.Role.STUDENT,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_signup_form_accepts_edu_bd_email_for_student(self):
        form_data = {
            'name': 'John Student',
            'email': 'student@dept.univ.edu.bd',
            'role': User.Role.STUDENT,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_signup_form_rejects_non_edu_email_for_instructor(self):
        form_data = {
            'name': 'Dr. Smith',
            'email': 'smith@yahoo.com',
            'role': User.Role.INSTRUCTOR,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn(
            "A valid university email (.edu or .edu.bd) is required for this role.",
            form.errors['email']
        )

    def test_signup_form_accepts_edu_email_for_instructor(self):
        form_data = {
            'name': 'Dr. Smith',
            'email': 'smith@university.edu',
            'role': User.Role.INSTRUCTOR,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_signup_form_rejects_non_edu_email_for_coordinator(self):
        form_data = {
            'name': 'Coordinator Alice',
            'email': 'alice@hotmail.com',
            'role': User.Role.COORDINATOR,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn(
            "A valid university email (.edu or .edu.bd) is required for this role.",
            form.errors['email']
        )

    def test_signup_form_accepts_edu_bd_email_for_coordinator(self):
        form_data = {
            'name': 'Coordinator Alice',
            'email': 'alice@university.edu.bd',
            'role': User.Role.COORDINATOR,
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        }
        form = SignUpForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    # -------------------------------------------------------------
    # AdminUserCreationForm Tests
    # -------------------------------------------------------------
    def test_admin_creation_form_rejects_non_edu_email_for_student(self):
        form_data = {
            'name': 'Student Bob',
            'email': 'bob@company.org',
            'role': User.Role.STUDENT,
            'password': 'Password123!',
            'is_active': True,
        }
        form = AdminUserCreationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn(
            "A valid university email (.edu or .edu.bd) is required for this role.",
            form.errors['email']
        )

    def test_admin_creation_form_accepts_edu_email_for_student(self):
        form_data = {
            'name': 'Student Bob',
            'email': 'bob@college.edu',
            'role': User.Role.STUDENT,
            'password': 'Password123!',
            'is_active': True,
        }
        form = AdminUserCreationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_creation_form_allows_non_edu_email_for_admin(self):
        form_data = {
            'name': 'System Admin',
            'email': 'admin@gmail.com',
            'role': User.Role.ADMIN,
            'password': 'Password123!',
            'is_active': True,
        }
        form = AdminUserCreationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_creation_form_allows_edu_email_for_admin(self):
        form_data = {
            'name': 'System Admin',
            'email': 'admin@university.edu',
            'role': User.Role.ADMIN,
            'password': 'Password123!',
            'is_active': True,
        }
        form = AdminUserCreationForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)

    # -------------------------------------------------------------
    # AdminUserUpdateForm Tests
    # -------------------------------------------------------------
    def test_admin_update_form_rejects_non_edu_email_for_student(self):
        user = User.objects.create_user(
            email='initial@university.edu',
            name='Student Charlie',
            role=User.Role.STUDENT,
            password='Password123!'
        )
        form_data = {
            'name': 'Student Charlie Updated',
            'email': 'charlie@gmail.com',
            'role': User.Role.STUDENT,
            'is_active': True,
        }
        form = AdminUserUpdateForm(data=form_data, instance=user)
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)
        self.assertIn(
            "A valid university email (.edu or .edu.bd) is required for this role.",
            form.errors['email']
        )

    def test_admin_update_form_accepts_edu_email_for_student(self):
        user = User.objects.create_user(
            email='initial@university.edu',
            name='Student Charlie',
            role=User.Role.STUDENT,
            password='Password123!'
        )
        form_data = {
            'name': 'Student Charlie Updated',
            'email': 'charlie_new@university.edu.bd',
            'role': User.Role.STUDENT,
            'is_active': True,
        }
        form = AdminUserUpdateForm(data=form_data, instance=user)
        self.assertTrue(form.is_valid(), form.errors)

    def test_admin_update_form_allows_non_edu_email_for_admin(self):
        admin = User.objects.create_superuser(
            email='admin@gmail.com',
            name='Super Admin',
            password='Password123!'
        )
        form_data = {
            'name': 'Super Admin Renamed',
            'email': 'new_admin@company.com',
            'role': User.Role.ADMIN,
            'is_active': True,
        }
        form = AdminUserUpdateForm(data=form_data, instance=admin)
        self.assertTrue(form.is_valid(), form.errors)


class EduEmailConstraintViewIntegrationTests(TestCase):
    """
    Integration tests verifying sign up and user management views enforce the
    educational email constraint for non-admin accounts.
    """

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            email='sara@gmail.com',
            name='Sara Admin',
            password='password123'
        )

    def test_signup_view_fails_with_non_edu_email(self):
        resp = self.client.post(reverse('signup'), {
            'name': 'Test Student',
            'email': 'test@gmail.com',
            'role': User.Role.STUDENT,
            'password1': 'ComplexPass123!',
            'password2': 'ComplexPass123!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email='test@gmail.com').exists())
        self.assertContains(resp, "A valid university email (.edu or .edu.bd) is required for this role.")

    def test_signup_view_succeeds_with_edu_email_and_redirects(self):
        resp = self.client.post(reverse('signup'), {
            'name': 'Valid Student',
            'email': 'valid@university.edu',
            'role': User.Role.STUDENT,
            'password1': 'ComplexPass123!',
            'password2': 'ComplexPass123!',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(email='valid@university.edu').exists())
        self.assertTrue(resp.redirect_chain)
        self.assertIn(reverse('student_dashboard'), resp.redirect_chain[0][0])

    def test_admin_user_create_view_fails_with_non_edu_student(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('admin_user_create'), {
            'name': 'Admin Created Student',
            'email': 'student@gmail.com',
            'role': User.Role.STUDENT,
            'password': 'Password123!',
            'is_active': True,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(email='student@gmail.com').exists())
        self.assertContains(resp, "A valid university email (.edu or .edu.bd) is required for this role.")

    def test_admin_user_create_view_succeeds_with_edu_student(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('admin_user_create'), {
            'name': 'Admin Created Student',
            'email': 'student@university.edu',
            'role': User.Role.STUDENT,
            'password': 'Password123!',
            'is_active': True,
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(email='student@university.edu').exists())
        self.assertIn(reverse('admin_user_management'), resp.redirect_chain[0][0])

    def test_admin_user_create_view_allows_non_edu_for_admin(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse('admin_user_create'), {
            'name': 'Secondary Admin',
            'email': 'secondary_admin@gmail.com',
            'role': User.Role.ADMIN,
            'password': 'Password123!',
            'is_active': True,
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(User.objects.filter(email='secondary_admin@gmail.com').exists())
        self.assertIn(reverse('admin_user_management'), resp.redirect_chain[0][0])
