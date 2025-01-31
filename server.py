from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import random
import string

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.db'
db = SQLAlchemy(app)
socketio = SocketIO(app)

rooms = {}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)


class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    questions = db.relationship('Question', backref='quiz', lazy=True)


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question_text = db.Column(db.String(500), nullable=False)
    question_type = db.Column(db.String(50), nullable=False)
    options = db.Column(db.PickleType, nullable=True)
    correct_answer = db.Column(db.String(500), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quiz.id'), nullable=False)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password, method='sha256')
        user = User(username=username, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('dashboard'))
        else:
            flash('Login failed. Check your username and/or password.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('index'))


@app.route('/create_room', methods=['POST'])
def create_room():
    room_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    rooms[room_code] = {'players': {}, 'questions': []}
    return redirect(url_for('room', room_code=room_code))


@app.route('/room/<room_code>')
def room(room_code):
    if room_code not in rooms:
        return 'Room not found!', 404
    return render_template('room.html', room_code=room_code)


@app.route('/create_quiz', methods=['GET', 'POST'])
def create_quiz():
    if 'user_id' not in session:
        flash('You need to be logged in to create a quiz.')
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'quiz_title' in request.form:
            title = request.form['quiz_title']
            user_id = session['user_id']
            new_quiz = Quiz(title=title, user_id=user_id)
            db.session.add(new_quiz)
            db.session.commit()
            flash('Quiz created successfully. Now add questions.')
            return render_template('create_quiz.html', quiz=new_quiz)
        elif 'question_text' in request.form:
            quiz_id = request.form['quiz_id']
            quiz = Quiz.query.get_or_404(quiz_id)
            question_type = request.form['question_type']
            question_text = request.form['question_text']
            if question_type == 'multiple_choice':
                options = {
                    'option1': request.form['option1'],
                    'option2': request.form['option2'],
                    'option3': request.form['option3'],
                    'option4': request.form['option4']
                }
                correct_answer = request.form['correct_answer']
                new_question = Question(question_text=question_text, question_type=question_type, options=options,
                                        correct_answer=correct_answer, quiz_id=quiz.id)
            elif question_type == 'true_false':
                correct_answer = request.form['true_false']
                new_question = Question(question_text=question_text, question_type=question_type,
                                        correct_answer=correct_answer, quiz_id=quiz.id)

            db.session.add(new_question)
            db.session.commit()
            flash('Question added successfully.')
            return render_template('create_quiz.html', quiz=quiz)

    return render_template('create_quiz.html')


@app.route('/quizzes')
def quizzes():
    if 'user_id' not in session:
        flash('You need to be logged in to view quizzes.')
        return redirect(url_for('login'))

    all_quizzes = Quiz.query.all()
    return render_template('quizzes.html', quizzes=all_quizzes)


@app.route('/edit_quiz/<int:quiz_id>', methods=['GET', 'POST'])
def edit_quiz(quiz_id):
    if 'user_id' not in session:
        flash('You need to be logged in to edit a quiz.')
        return redirect(url_for('login'))

    quiz = Quiz.query.get_or_404(quiz_id)

    if quiz.user_id != session['user_id']:
        flash('You do not have permission to edit this quiz.')
        return redirect(url_for('quizzes'))

    if request.method == 'POST':
        title = request.form['quiz_title']
        quiz.title = title
        db.session.commit()
        flash('Quiz updated successfully.')
        return redirect(url_for('quizzes'))

    return render_template('edit_quiz.html', quiz=quiz)


@app.route('/start_quiz/<room_code>', methods=['GET', 'POST'])
def start_quiz(room_code):
    if 'user_id' not in session:
        flash('You need to be logged in to start a quiz.')
        return redirect(url_for('login'))

    if room_code not in rooms:
        return 'Room not found!', 404

    room = rooms[room_code]
    room['current_question'] = 0
    room['start_time'] = datetime.now()
    room['scores'] = {sid: 0 for sid in room['players']}

    question = get_next_question(room_code)
    emit('next_question', question, room=room_code)

    return render_template('room.html', room_code=room_code)


def get_next_question(room_code):
    room = rooms[room_code]
    quiz = Quiz.query.get(room['quiz_id'])
    if room['current_question'] >= len(quiz.questions):
        return None
    question = quiz.questions[room['current_question']]
    return {'id': question.id, 'text': question.question_text, 'options': question.options}


@socketio.on('join')
def on_join(data):
    room_code = data['room']
    player_name = data['name']
    join_room(room_code)
    rooms[room_code]['players'][request.sid] = player_name
    emit('player_joined', {'name': player_name}, room=room_code)


@socketio.on('submit_answer')
def on_submit_answer(data):
    room_code = data['room']
    answer = data['answer']
    player_sid = request.sid

    room = rooms[room_code]
    question_id = room['current_question']
    quiz = Quiz.query.get(room['quiz_id'])
    question = quiz.questions[question_id]

    end_time = datetime.now()
    time_taken = (end_time - room['start_time']).total_seconds()

    if answer == question.correct_answer:
        score = max(1000 - int(time_taken * 100), 0)
        room['scores'][player_sid] += score
        emit('answer_result', {'correct': True, 'score': score}, to=player_sid)
    else:
        emit('answer_result', {'correct': False, 'score': 0}, to=player_sid)

    room['current_question'] += 1
    if room['current_question'] < len(quiz.questions):
        room['start_time'] = datetime.now()
        next_question = get_next_question(room_code)
        emit('next_question', next_question, room=room_code)
    else:
        emit('quiz_finished', {'scores': room['scores']}, room=room_code)


if __name__ == '__main__':
    socketio.run(app, debug=True)
