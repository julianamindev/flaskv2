from flask_login import current_user
from flask_wtf import FlaskForm
# from flask_wtf.file import FileField, FileAllowed
from wtforms import BooleanField, FileField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError

from flaskv2.models import User

class RegistrationForm(FlaskForm):
    username            = StringField('Username', validators=[DataRequired(), Length(min=2, max=50)])
    email               = StringField('Email', validators=[DataRequired(), Email()])
    is_admin            = BooleanField('Grant Admin Privileges')
    submit              = SubmitField('Register User')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        # If user already exists in database, raise error
        if user:
            raise ValidationError('That username is already taken.')
        
    def validate_email(self, email):
        email = User.query.filter_by(email=email.data).first()
        # If email already exists in database, raise error
        if email:
            raise ValidationError('That email is already taken.')

class LoginForm(FlaskForm):
    username    = StringField('Username', validators=[DataRequired()])
    password    = PasswordField('Password', validators=[DataRequired()])
    submit      = SubmitField('Login')

class ResetPasswordForm(FlaskForm):
    old_password        = PasswordField('Temporary Password', validators=[DataRequired()])
    new_password        = PasswordField('New Password', validators=[DataRequired(), Length(min=8, max=50)])
    confirm_password    = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('new_password')])
    submit              = SubmitField('Reset Password')

class ForgotPasswordForm(FlaskForm):
    email               = StringField('Email', validators=[DataRequired(), Email()])
    submit              = SubmitField('Reset Password')

    def validate_email(self, email):
        email = User.query.filter_by(email=email.data).first()
        # If email already exists in database, raise error
        if email is None:
            raise ValidationError('There is no account with that email.')