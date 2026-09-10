from django import forms
from .models import Project ,Team
from accounts.models import User
from .models import CourseSection

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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.fields['members'].initial = self.instance.members.all()


class CourseSectionForm(forms.ModelForm):
    class Meta:
        model = CourseSection
        fields = ['course', 'section_name', 'instructor']
        widgets = {
            'course': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm bg-white'}),
            'section_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm', 'placeholder': 'e.g. Section C'}),
            'instructor': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm bg-white'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instructor'].queryset = User.objects.filter(role='INSTRUCTOR')
        self.fields['instructor'].required = False


class AssignInstructorForm(forms.ModelForm):
    class Meta:
        model = CourseSection
        fields = ['instructor']
        widgets = {
            'instructor': forms.Select(attrs={'class': 'w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm bg-white'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restrict choices strictly to users with the INSTRUCTOR role
        self.fields['instructor'].queryset = User.objects.filter(role='INSTRUCTOR')
        self.fields['instructor'].required = False
        self.fields['instructor'].label = ""