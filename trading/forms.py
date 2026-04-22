from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.forms import ModelForm

FRIENDLY_PASSWORD_ERRORS = {
    'password_too_short':       'Password must be at least 8 characters.',
    'password_too_common':      'This password is too common — choose something more unique.',
    'password_entirely_numeric':'Password can\'t be entirely numeric.',
    'password_too_similar':     'Password is too similar to your username.',
}


class RegistrationForm(UserCreationForm):
    def _post_clean(self):
        # Run ModelForm's _post_clean to populate self.instance from form data.
        # We skip UserCreationForm's version because it calls validate_password
        # with Django's default (technical) error messages — we re-run it below
        # with friendly messages instead.
        ModelForm._post_clean(self)

        password = self.cleaned_data.get('password2')
        if password:
            try:
                validate_password(password, self.instance)
            except ValidationError as exc:
                friendly = [
                    FRIENDLY_PASSWORD_ERRORS.get(err.code, str(err.message))
                    for err in exc.error_list
                ]
                self.add_error('password2', friendly)
