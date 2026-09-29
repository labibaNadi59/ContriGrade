from django import forms
from .models import User
from django.contrib.auth import get_user_model
from django.conf import settings
import requests

class SignUpForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}))

    class Meta:
        model = User
        fields = ['name', 'email', 'role', 'password']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'email': forms.EmailInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'role': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['role'].choices = [
            choice for choice in User.Role.choices if choice[0] != User.Role.ADMIN
        ]

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class AdminUserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}))

    class Meta:
        model = User
        fields = ['email', 'name', 'role', 'password', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'role': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class AdminUserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'name', 'role', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'role': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'h-4 w-4 text-blue-600 border-gray-300 rounded'}),
        }


User = get_user_model()


class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['name', 'github_username']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3.5 py-2.5 bg-gray-50 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none',
            }),
            'github_username': forms.TextInput(attrs={
                'class': 'w-full px-3.5 py-2.5 bg-gray-50 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none rounded-l-none border-l-0',
                'placeholder': 'e.g., rahim@2026'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If the user is NOT a student, remove the github field entirely
        if self.instance and self.instance.role != 'STUDENT':
            self.fields.pop('github_username', None)

    def clean_github_username(self):
        username = self.cleaned_data.get('github_username')
        if username:
            username = username.strip().lstrip('@')

            # API Validation to ensure the user exists on GitHub
            token = getattr(settings, 'GITHUB_API_TOKEN', None)
            headers = {"Accept": "application/vnd.github.v3+json"}
            if token:
                headers["Authorization"] = f"token {token}"

            try:
                response = requests.get(f"https://api.github.com/users/{username}", headers=headers, timeout=5)
                if response.status_code == 404:
                    raise forms.ValidationError(f"GitHub user '{username}' not found. Please check your spelling.")
            except requests.RequestException:
                # If network fails, don't block the user from saving, just skip validation
                pass

        return username





