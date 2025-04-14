from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, emit, join_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = '2747b5affd6f01212c6c8e4eff8e650a609ba22334662ed7fed7ba79adcfffb0'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tic_tac_toe.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ----------------------------
# Models
# ----------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    total_points = db.Column(db.Integer, default=0)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Game(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    board = db.Column(db.String(9), nullable=False, default=' ' * 9)
    current_turn = db.Column(db.String(1), nullable=False, default='X')
    winner = db.Column(db.String(1), nullable=True)  # 'X', 'O', or 'D' for draw
    player_x_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    player_o_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def as_dict(self):
        return {
            'id': self.id,
            'board': self.board,
            'current_turn': self.current_turn,
            'winner': self.winner,
            'player_x_id': self.player_x_id,
            'player_o_id': self.player_o_id,
            'created_at': self.created_at.isoformat()
        }

class GameResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    points = db.Column(db.Integer, default=10)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey('game.id'))
    username = db.Column(db.String(80))
    message = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ----------------------------
# Login Manager
# ----------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ----------------------------
# In-Memory Online Users Tracking
# ----------------------------
online_users = {}  # {user_id: request.sid}

# ----------------------------
# Routes
# ----------------------------
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('register'))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful. Please log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    online_users.pop(current_user.id, None)
    logout_user()
    return redirect(url_for('index'))

@app.route('/leaderboard')
@login_required
def leaderboard():
    now = datetime.utcnow()
    daily = db.session.query(User.username, db.func.sum(GameResult.points))\
        .join(GameResult).filter(GameResult.timestamp > now - timedelta(days=1))\
        .group_by(User.id).order_by(db.func.sum(GameResult.points).desc()).all()
    weekly = db.session.query(User.username, db.func.sum(GameResult.points))\
        .join(GameResult).filter(GameResult.timestamp > now - timedelta(days=7))\
        .group_by(User.id).order_by(db.func.sum(GameResult.points).desc()).all()
    return render_template('leaderboard.html', daily=daily, weekly=weekly)

@app.route('/game/<int:game_id>')
@login_required
def game_view(game_id):
    game = Game.query.get_or_404(game_id)
    symbol = 'X' if game.player_x_id == current_user.id else 'O'
    return render_template('game.html', game_id=game.id, symbol=symbol, user=current_user)

@app.route('/new_game', methods=['POST'])
@login_required
def new_game():
    data = request.get_json()
    opponent_id = data.get('opponent_id')
    if not opponent_id:
        return jsonify({'error': 'No opponent specified'}), 400
    game = Game(player_x_id=current_user.id, player_o_id=opponent_id)
    db.session.add(game)
    db.session.commit()
    return jsonify({'game_id': game.id})

@app.route('/move/<int:game_id>', methods=['POST'])
@login_required
def move(game_id):
    game = Game.query.get_or_404(game_id)
    data = request.get_json()
    pos = data.get('position')
    symbol = data.get('symbol')
    if pos is None or symbol is None:
        return jsonify({'error': 'Invalid move data'}), 400
    if game.board[pos] != ' ' or game.winner or game.current_turn != symbol:
        return jsonify({'error': 'Invalid move'}), 400
    if (symbol == 'X' and game.player_x_id != current_user.id) or \
       (symbol == 'O' and game.player_o_id != current_user.id):
        return jsonify({'error': 'Unauthorized move'}), 403

    board = list(game.board)
    board[pos] = symbol
    game.board = ''.join(board)

    wins = [(0,1,2), (3,4,5), (6,7,8), (0,3,6), (1,4,7), (2,5,8), (0,4,8), (2,4,6)]
    for a, b, c in wins:
        if game.board[a] == game.board[b] == game.board[c] != ' ':
            game.winner = symbol
            winner_id = game.player_x_id if symbol == 'X' else game.player_o_id
            user = User.query.get(winner_id)
            if user:
                user.total_points += 10
                db.session.add(GameResult(user_id=user.id, points=10))
            break

    if not game.winner and ' ' not in game.board:
        game.winner = 'D'

    if not game.winner:
        game.current_turn = 'O' if symbol == 'X' else 'X'

    db.session.commit()
    socketio.emit('game_update', {
        'game_id': game.id,
        'board': game.board,
        'turn': game.current_turn,
        'winner': game.winner
    }, room=f'game_{game.id}')
    return jsonify({'status': 'ok'})

@app.route('/online_users')
@login_required
def get_online_users():
    users = [
        {'id': uid, 'username': User.query.get(uid).username}
        for uid in online_users.keys() if uid != current_user.id
    ]
    return jsonify(users)

# ----------------------------
# Socket.IO Events
# ----------------------------
@socketio.on('connect')
def on_connect():
    if current_user.is_authenticated:
        online_users[current_user.id] = request.sid
        emit('user_online', {'id': current_user.id, 'username': current_user.username}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    if current_user.is_authenticated:
        online_users.pop(current_user.id, None)
        emit('user_offline', {'id': current_user.id}, broadcast=True)

@socketio.on('join')
def on_join(data):
    game_id = data.get('game_id')
    if game_id:
        join_room(f'game_{game_id}')
        msgs = ChatMessage.query.filter_by(game_id=game_id).order_by(ChatMessage.timestamp.asc()).all()
        emit('chat_history', [{
            'username': m.username,
            'message': m.message,
            'timestamp': m.timestamp.strftime('%H:%M')
        } for m in msgs])

@socketio.on('challenge')
def on_challenge(data):
    to_user_id = data.get('to_user_id')
    to_sid = online_users.get(to_user_id)
    if to_sid:
        emit('receive_challenge', {
            'from_user_id': current_user.id,
            'from_username': current_user.username
        }, room=to_sid)

@socketio.on('accept_challenge')
def on_accept_challenge(data):
    # Data should contain 'from_user_id' (the challenger)
    challenger_id = data.get('from_user_id')
    challenger_sid = online_users.get(challenger_id)
    acceptor_sid = request.sid
    # Notify both users that the challenge has been accepted.
    emit('challenge_accepted', {'message': 'Challenge accepted!'}, room=challenger_sid)
    emit('challenge_accepted', {'message': 'Challenge accepted!'}, room=acceptor_sid)
    # Countdown: emit countdown events every second.
    for count in range(5, 0, -1):
        emit('challenge_countdown', {'count': count}, room=challenger_sid)
        emit('challenge_countdown', {'count': count}, room=acceptor_sid)
        socketio.sleep(1)
    # After countdown, create a new game.
    game = Game(player_x_id=challenger_id, player_o_id=current_user.id)
    db.session.add(game)
    db.session.commit()
    emit('game_start', {'game_id': game.id}, room=challenger_sid)
    emit('game_start', {'game_id': game.id}, room=acceptor_sid)

@socketio.on('chat_message')
def on_chat(data):
    game_id = data.get('game_id')
    message = data.get('message')
    if game_id and message:
        chat = ChatMessage(game_id=game_id, username=current_user.username, message=message)
        db.session.add(chat)
        db.session.commit()
        emit('chat_message', {
            'username': current_user.username,
            'message': message,
            'timestamp': chat.timestamp.strftime('%H:%M')
        }, room=f'game_{game_id}')

# ----------------------------
# App Initialization
# ----------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)
