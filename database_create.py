from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    # ... (保持不變)
    id = db.Column(db.Integer, primary_key=True)
    oid = db.Column(db.String(100), unique=True, nullable=False) # Azure AD Object ID
    upn = db.Column(db.String(100), unique=True, nullable=False) # User Principal Name (Email)
    is_admin = db.Column(db.Boolean, default=False)
    prompts = db.relationship('Prompt', backref='author', lazy=True)

class Prompt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False, default='其他')
    description = db.Column(db.Text, nullable=True)
    tags = db.Column(db.String(500), nullable=True)
    is_shared = db.Column(db.Boolean, default=False)
    is_approved = db.Column(db.Boolean, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f"Prompt('{self.title}', Category:{self.category}, Approved:{self.is_approved})"

    def get_tags(self):
        if not self.tags:
            return []
        return [tag.strip() for tag in self.tags.split(',')]

    def set_tags(self, tag_list):
        self.tags = ','.join(tag_list) if tag_list else None