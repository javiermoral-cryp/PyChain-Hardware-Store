from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Perfil
import os


class RegistroClienteForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'password1', 'password2']

    def save(self, commit=True):
        user = super().save(commit)
        Perfil.objects.create(user=user, administrador_negocio=False)
        return user

class RegistroAdminForm(UserCreationForm):
    username = forms.CharField(max_length=150)
    password1 = forms.CharField(label="contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="confirmar contraseña", widget=forms.PasswordInput)
    codigo_secreto = forms.CharField(label="Codigo secreto", max_length=50)

    class Meta:
        model = User
        fields = ['username', 'password1', 'password2']

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        codigo = cleaned_data.get("codigo_secreto")

        if password1 != password2:
            raise forms.ValidationError("Las contraseñas no coinciden.")

        if codigo != os.environ.get("ADMIN_SECRET_CODE"):
            raise forms.ValidationError("Código secreto incorrecto")

        return cleaned_data

    def save(self, commit=True):
        user = User(username=self.cleaned_data["username"])
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            Perfil.objects.create(user=user, administrador_negocio=True)
        return user


class PerfilForm(forms.ModelForm):
    class Meta:
        model = Perfil
        fields =["user", "administrador_negocio"]