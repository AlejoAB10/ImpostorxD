from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit, join_room
import random
import string
import unicodedata

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secreto_super_secreto'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- DATA (SecretWord, Category, FakeWordForImpostor) ---
CATEGORIES = {
    "Fácil": [
        # Originales
        ("Fernet", "Bebidas", "Coca-Cola"), 
        ("Pizza", "Comida", "Hamburguesa"), 
        ("Gato", "Animales", "Perro"), 
        ("Futbol", "Deportes", "Basquet"),
        # Nuevas (Lugares comunes)
        ("Playa", "Lugares", "Piscina"),
        ("Escuela", "Lugares", "Universidad"),
        ("Hospital", "Lugares", "Farmacia"),
        ("Aeropuerto", "Lugares", "Terminal"),
        ("Cine", "Salidas", "Teatro"),
        ("Supermercado", "Lugares", "Almacén"),
        ("Biblioteca", "Lugares", "Librería"),
        ("Gimnasio", "Lugares", "Parque"),
        ("Hotel", "Lugares", "Airbnb"),
        ("Restaurante", "Salidas", "Bar"),
        ("Camping", "Aire Libre", "Picnic"),
        ("Peluquería", "Lugares", "Barbería"),
        ("Iglesia", "Lugares", "Catedral"),
        ("Farmacia", "Lugares", "Hospital"),
        ("Estación de tren", "Transporte", "Subte"),
        ("Parque de diversiones", "Salidas", "Circo"),
        ("Casino", "Salidas", "Bingo"),
        ("Zoológico", "Paseos", "Granja"),
        ("Museo", "Paseos", "Galería"),
        ("Estadio de fútbol", "Lugares", "Cancha de barrio"),
    ],
    "Media": [
        # Originales
        ("Messi", "Famosos", "Cristiano"), 
        ("Sushi", "Comida", "Pescado"), 
        ("Netflix", "Apps", "YouTube"),
        ("Python", "Tech", "Código"), 
        ("Guitarra", "Música", "Violín"),
        # Nuevas (Objetos)
        ("Celular", "Tecnología", "Tablet"),
        ("Llaves", "Objetos", "Candado"),
        ("Mochila", "Objetos", "Valija"),
        ("Sillón", "Muebles", "Silla"),
        ("Mesa", "Muebles", "Escritorio"),
        ("Zapatillas", "Ropa", "Ojotas"),
        ("Botella", "Objetos", "Vaso"),
        ("Reloj", "Accesorios", "Pulsera"),
        ("Auriculares", "Tecnología", "Parlante"),
        ("Cuaderno", "Útiles", "Agenda"),
        ("Microondas", "Electrodomésticos", "Horno"),
        ("Espejo", "Objetos", "Vidrio"),
        ("Almohada", "Cama", "Colchón"),
        ("Control remoto", "Tecnología", "Joystick"),
        ("Ventilador", "Clima", "Aire Acondicionado"),
        ("Tostadora", "Cocina", "Sandwichera"),
        ("Lámpara", "Iluminación", "Linterna"),
        ("Paraguas", "Clima", "Piloto"),
        ("Escoba", "Limpieza", "Aspiradora"),
        ("Cámara de fotos", "Tecnología", "Celular"),
    ],
    "Difícil": [
        # Originales
        ("Inflación", "Economía", "Pobreza"), 
        ("Metaverso", "Tech", "Realidad Virtual"),
        ("Paradoja", "Filosofía", "Contradicción"), 
        ("Melancolía", "Sentimientos", "Tristeza"), 
        ("Burocracia", "Sociedad", "Trámite"),
        # Nuevas (Animales Exóticos/Específicos para confundir)
        ("Caballo", "Animales", "Burro"),
        ("Elefante", "Animales", "Rinoceronte"),
        ("Tiburón", "Animales", "Delfín"), # Confuso con Delfín real
        ("Águila", "Animales", "Halcón"),
        ("León", "Animales", "Tigre"),
        ("Pingüino", "Animales", "Pato"),
        ("Mono", "Animales", "Gorila"),
        ("Delfín", "Animales", "Ballena"),
    ],
    "Picante": [
        ("Suegra", "Familia", "Madre"), 
        ("Ex", "Relaciones", "Amigo"), 
        ("Tinder", "Apps", "Instagram"),
        ("Motel", "Lugares", "Hotel"), 
        ("Resaca", "Estados", "Borrachera")
    ]
}

# --- HELPER ---
def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn').lower().strip()

# --- GAME LOGIC ---
games = {}

class Game:
    def __init__(self, code):
        self.code = code
        self.players = {}
        self.state = "LOBBY"
        self.secret_word = ""
        self.hint_category = ""
        self.impostor_word = ""
        self.impostor_sid = None
        self.turn_order = []
        self.difficulty = "Media"

    def add_player(self, sid, name):
        self.players[sid] = {'name': name, 'role': None, 'votes': 0, 'voted': False}

    def remove_player(self, sid):
        if sid in self.players: del self.players[sid]

    def start_round(self, difficulty="Media"):
        if len(self.players) < 3: return False, "Min 3 jugadores."
        
        self.difficulty = difficulty
        if difficulty not in CATEGORIES: difficulty = "Media"
        
        # Tuple: (Real, Cat, Fake)
        word_data = random.choice(CATEGORIES[difficulty])
        self.secret_word = word_data[0]
        self.hint_category = word_data[1]
        self.impostor_word = word_data[2]

        sids = list(self.players.keys())
        self.impostor_sid = random.choice(sids)
        self.turn_order = random.sample(sids, len(sids))

        for sid in sids:
            self.players[sid]['role'] = 'Impostor' if sid == self.impostor_sid else 'Ciudadano'
            self.players[sid]['votes'] = 0
            self.players[sid]['voted'] = False
        
        self.state = "HINT"
        return True, "Juego iniciado"

    def cast_vote(self, voter_sid, target_sid):
        if self.state != "VOTING": return False
        if self.players[voter_sid]['voted']: return False
        if target_sid in self.players:
            self.players[target_sid]['votes'] += 1
            self.players[voter_sid]['voted'] = True
            return True
        return False

    def all_voted(self):
        return all(p['voted'] for p in self.players.values())

    def check_vote_result(self):
        sorted_players = sorted(self.players.items(), key=lambda x: x[1]['votes'], reverse=True)
        if not sorted_players: return "TIE", None
        most_voted = sorted_players[0]
        if len(sorted_players) > 1 and sorted_players[1][1]['votes'] == most_voted[1]['votes']:
             return "TIE", None
        return "DECIDED", most_voted[0]

    def resolve_impostor_guess(self, guess):
        return normalize(guess) == normalize(self.secret_word)

    def to_dict(self):
        return {
            "code": self.code,
            "players": [{"name": p['name'], "sid": s, "votes": p['votes'], "voted": p['voted']} for s, p in self.players.items()],
            "state": self.state,
            "category": self.hint_category,
            "turn_order": [self.players[sid]['name'] for sid in self.turn_order],
            "player_count": len(self.players)
        }

# --- ROUTES ---
@app.route('/')
def index(): return render_template('index.html')

# --- SOCKET ---
def send_sys(room, text): emit('receive_chat', {'sender': 'Juego', 'text': text, 'type': 'system'}, room=room)

@socketio.on('create_game')
def handle_create(data):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    games[code] = Game(code)
    games[code].add_player(request.sid, data.get('name', 'Host'))
    join_room(code)
    emit('game_joined', {'code': code}, room=request.sid)
    emit('update_game', games[code].to_dict(), room=code)
    send_sys(code, f"Sala creada por {data.get('name')}.")

@socketio.on('join_game')
def handle_join(data):
    code = data.get('code', '').upper()
    name = data.get('name', 'Player')
    if code in games:
        games[code].add_player(request.sid, name)
        join_room(code)
        emit('game_joined', {'code': code}, room=request.sid)
        emit('update_game', games[code].to_dict(), room=code)
        send_sys(code, f"{name} entró.")
    else: emit('error_message', {'msg': 'Sala no existe'})

@socketio.on('start_game')
def handle_start(data):
    code = data.get('code')
    if code in games:
        game = games[code]
        ok, msg = game.start_round(data.get('difficulty', 'Media'))
        if ok:
            emit('update_game', game.to_dict(), room=code)
            send_sys(code, "¡Empezó la partida!")
            emit('spotlight_announce', {'player': game.players[game.turn_order[0]]['name']}, room=code)
            
            # Send Roles
            for sid, p in game.players.items():
                if p['role'] == 'Ciudadano':
                    secret = game.secret_word
                    is_impo = False
                else:
                    # Impostor gets Fake Word
                    secret = game.impostor_word
                    is_impo = True
                
                emit('role_assigned', {
                    "role": "Jugador",
                    "is_impostor": is_impo,
                    "secret": secret,
                    "category": game.hint_category
                }, room=sid)

@socketio.on('start_voting')
def handle_vote_start(data):
    code = data.get('code')
    if code in games:
        games[code].state = "VOTING"
        emit('update_game', games[code].to_dict(), room=code)
        send_sys(code, "A Votar.")

@socketio.on('vote_player')
def handle_vote(data):
    code = data.get('code')
    if code in games:
        game = games[code]
        if game.cast_vote(request.sid, data.get('target_sid')):
            emit('vote_update', {}, room=code)
            if game.all_voted():
                status, sid = game.check_vote_result()
                if status == "TIE":
                    game.state = "FINISHED"
                    emit('game_over', {"result": "TIE", "impostor": game.players[game.impostor_sid]['name'], "secret": game.secret_word}, room=code)
                    send_sys(code, "Empate. Nadie sale.")
                elif sid == game.impostor_sid:
                    game.state = "GUESSING"
                    emit('update_game', game.to_dict(), room=code)
                    emit('impostor_guess_start', {}, room=game.impostor_sid)
                    send_sys(code, "¡Impostor atrapado! Última oportunidad...")
                else:
                    game.state = "FINISHED"
                    emit('game_over', {"result": "WIN", "winner": "IMPOSTOR", "voted_out": game.players[sid]['name'], "impostor": game.players[game.impostor_sid]['name'], "secret": game.secret_word}, room=code)
                    send_sys(code, "¡Expulsaron a un inocente!")

@socketio.on('impostor_guess')
def handle_guess(data):
    code = data.get('code')
    if code in games:
        game = games[code]
        win = game.resolve_impostor_guess(data.get('guess', ''))
        game.state = "FINISHED"
        emit('game_over', {
            "result": "WIN", 
            "winner": "IMPOSTOR" if win else "CIUDADANOS",
            "impostor": game.players[game.impostor_sid]['name'], 
            "secret": game.secret_word,
            "guess": data.get('guess'),
            "guess_correct": win
        }, room=code)

@socketio.on('send_chat')
def handle_chat(data):
    code = data.get('code')
    if code in games:
        name = games[code].players.get(request.sid, {}).get('name', '?')
        emit('receive_chat', {'sender': name, 'text': data.get('message'), 'type': 'player'}, room=code)

@socketio.on('reset_game')
def handle_reset(data):
    code = data.get('code')
    if code in games:
        games[code].state = "LOBBY"
        for p in games[code].players.values(): 
            p['role']=None; p['votes']=0; p['voted']=False
        emit('update_game', games[code].to_dict(), room=code)
        send_sys(code, "Reiniciando...")

@socketio.on('disconnect')
def handle_disc():
    for code, game in games.items():
        if request.sid in game.players:
            game.remove_player(request.sid)
            emit('update_game', game.to_dict(), room=code)
            if not game.players: del games[code]
            break

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)