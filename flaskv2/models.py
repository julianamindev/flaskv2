
from flask_login import UserMixin
from flaskv2 import db, login_manager
from flask import current_app
from itsdangerous import URLSafeTimedSerializer as Serializer

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id              = db.Column(db.Integer, primary_key=True)
    username        = db.Column(db.String(50), unique=True, nullable=False)
    email           = db.Column(db.String(100), unique=True, nullable=False)
    password        = db.Column(db.String(200), nullable=False)
    created_date    = db.Column(db.DateTime, server_default=db.func.now())
    is_active       = db.Column(db.Boolean, default=False)
    last_login      = db.Column(db.DateTime)
    is_admin        = db.Column(db.Boolean, default=False)

    def is_root(self):
        return self.username == 'root'
    
    def can_delete(self, target_user):

        # root can delete anyone except self
        if self.is_root():
            return self != target_user  
        
        # Admins can delete non-admin, non-root users
        if self.is_admin:
            return not target_user.is_admin and not target_user.is_root()
        
        return False
    
    def can_grant_admin(self, target_user):
        return self.is_root() and not target_user.is_admin and not target_user.is_root()
    
    def can_revoke_admin(self, target_user):
        return self.is_root() and target_user.is_admin and not target_user.is_root()

    def get_reset_token(self):
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})
    
    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, max_age=expires_sec)['user_id']
        except:
            return None
        
        return User.query.get(user_id)