from django import forms
from .models import Project ,Team
from accounts.models import User
class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['section', 'title', 'description', 'deadline']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'placeholder': 'e.g., Final Capstone'}),
            'description': forms.Textarea(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'rows': 3}),
            'section': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),

            'deadline': forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'w-full px-3 py-2 border rounded-lg'}),
        }


class TeamForm(forms.ModelForm):
    # This field grabs all students so the instructor can select multiple at once
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(role='STUDENT'),
        widget=forms.SelectMultiple(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'size': '5'}),
        help_text="Hold Ctrl (or Cmd) to select multiple students.",
        required=False
    )

    class Meta:
        model = Team
        fields = ['project', 'team_name']
        widgets = {
            'project': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'team_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'placeholder': 'e.g., VoltShare'}),
        }