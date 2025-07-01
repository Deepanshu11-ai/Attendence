from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Use PostgreSQL on Render, fallback to SQLite locally
uri = os.environ.get('DATABASE_URL', 'sqlite:///attendance.db')
if uri.startswith('postgres://'):
    uri = uri.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# MODELS
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    password = db.Column(db.String(150))
    subjects = db.relationship('Subject', backref='owner', lazy=True)

class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    manual_total = db.Column(db.Integer, default=0)
    manual_present = db.Column(db.Integer, default=0)
    attendances = db.relationship('Attendance', backref='subject', lazy=True, cascade='all, delete')

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(10))  # "Present" or "Absent"
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'))

@login_manager.user_loader

def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    return redirect(url_for('predict'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip().lower()
        full_name = request.form['full_name'].strip()
        password = request.form['password']
        if not username or not password or not email or not full_name:
            flash("All fields are required.")
            return render_template('register.html')
        if len(password) < 6:
            flash("Password must be at least 6 characters long.")
            return render_template('register.html')
        if User.query.filter_by(username=username).first():
            flash("Username already exists. Please choose another.")
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash("Email already registered. Please use another.")
            return render_template('register.html')
        hashed_password = generate_password_hash(password)
        user = User(username=username, email=email, full_name=full_name, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash("Registered successfully! Login now.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash("Logged in successfully!")
            return redirect(url_for('dashboard'))
        flash("Invalid credentials")
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    return render_template('dashboard.html', subjects=subjects)

@app.route('/add_subject', methods=['GET', 'POST'])
@login_required
def add_subject():
    if request.method == 'POST':
        name = request.form['name']
        manual_total = int(request.form.get('manual_total') or 0)
        manual_present = int(request.form.get('manual_present') or 0)

        if manual_present > manual_total:
            flash("Present cannot be more than total.")
            return redirect(url_for('add_subject'))

        subject = Subject(name=name, user_id=current_user.id,
                          manual_total=manual_total, manual_present=manual_present)
        db.session.add(subject)
        db.session.commit()
        flash("Subject added successfully")
        return redirect(url_for('dashboard'))
    return render_template('add_subject.html')

@app.route('/delete_subject/<int:id>', methods=['POST'])
@login_required
def delete_subject(id):
    subject = Subject.query.get_or_404(id)
    if subject.owner != current_user:
        flash("Unauthorized")
        return redirect(url_for('dashboard'))
    db.session.delete(subject)
    db.session.commit()
    flash("Subject deleted")
    return redirect(url_for('dashboard'))

@app.route('/mark/<int:subject_id>/<status>', methods=['POST'])
def mark_attendance(subject_id, status):
    if not current_user.is_authenticated:
        flash("⚠️ You must log in to track attendance!")
        return redirect(url_for('login'))

    today = date.today()
    existing = Attendance.query.filter_by(subject_id=subject_id, date=today).first()
    if existing:
        flash("Attendance already marked today")
    else:
        attendance = Attendance(subject_id=subject_id, status=status)
        db.session.add(attendance)
        db.session.commit()
        flash(f"Marked {status}")
    return redirect(url_for('dashboard'))

@app.route('/predict')
def predict():
    if not current_user.is_authenticated:
        flash("👀 You're not logged in! You can calculate but not save.")
        return render_template("predictor.html", predictions=[])

    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    results = []

    for sub in subjects:
        total = len(sub.attendances) + sub.manual_total
        present = len([a for a in sub.attendances if a.status == 'Present']) + sub.manual_present
        if total == 0:
            continue
        current_percent = (present / total) * 100
        after_leave = (present / (total + 1)) * 100
        results.append({
            "name": sub.name,
            "current": round(current_percent, 2),
            "after_leave": round(after_leave, 2),
            "status": "✅ Safe" if after_leave >= 75 else "❌ Risky"
        })

    return render_template("predictor.html", predictions=results)

@app.route('/predict_leaves', methods=['GET', 'POST'])
def predict_leaves():
    if not current_user.is_authenticated:
        flash("👀 You're not logged in! You can calculate but not save.")
        return render_template("predict_leaves.html", predictions=[], subjects=[])

    subjects = Subject.query.filter_by(user_id=current_user.id).all()
    predictions = []

    if request.method == 'POST':
        for sub in subjects:
            future_leaves = int(request.form.get(f"leaves_{sub.id}", 0))
            total = len(sub.attendances) + sub.manual_total
            present = len([a for a in sub.attendances if a.status == 'Present']) + sub.manual_present
            if total == 0:
                continue
            current_percent = (present / total) * 100
            future_total = total + future_leaves
            future_percent = (present / future_total) * 100
            predictions.append({
                "name": sub.name,
                "current": round(current_percent, 2),
                "future_percent": round(future_percent, 2),
                "verdict": "✅ Safe" if future_percent >= 75 else "❌ Not Safe"
            })

    return render_template("predict_leaves.html", predictions=predictions, subjects=subjects)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)