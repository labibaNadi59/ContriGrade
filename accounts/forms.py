from django import forms
from .models import User


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

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user