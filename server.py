from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit, join_room
import random
import string

app = Flask(__name__)
socketio = SocketIO(app)

rooms = {}


@app.route('/')
def index():
    return render_template('index.html')


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


@socketio.on('join')
def on_join(data):
    room_code = data['room']
    player_name = data['name']
    join_room(room_code)
    rooms[room_code]['players'][request.sid] = player_name
    emit('player_joined', {'name': player_name}, room=room_code)


if __name__ == '__main__':
    socketio.run(app, debug=True)
