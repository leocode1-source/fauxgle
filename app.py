import logging
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from flask import Flask, abort, make_response, render_template_string, request
from duckduckgo_search import DDGS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024  # Les recherches sont très petites.

# Configuration
MAX_QUERY_LENGTH = 200
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fauxgle")

# Limiteur simple en mémoire. Pour plusieurs instances Render, utiliser un
# stockage partagé (Redis) afin que la limite soit commune à toutes les instances.
_requests_by_ip = defaultdict(deque)

BASE_STYLE = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body {
    font-family: Arial, sans-serif; margin: 0; color: #202124; background: #fff;
}
.creator { position: fixed; top: 12px; left: 16px; color: #666; font-size: 13px; }
.logo { font-size: 76px; font-weight: 700; letter-spacing: -5px; margin-bottom: 24px; }
.logo span:nth-child(1) { color: #4285F4; }
.logo span:nth-child(2) { color: #EA4335; }
.logo span:nth-child(3) { color: #FBBC05; }
.logo span:nth-child(4) { color: #4285F4; }
.logo span:nth-child(5) { color: #34A853; }
.logo span:nth-child(6) { color: #EA4335; }
.search-form { width: min(90vw, 560px); display: flex; gap: 8px; }
.search-input {
    min-width: 0; flex: 1; padding: 13px 20px; font-size: 16px;
    border: 1px solid #dfe1e5; border-radius: 24px; outline: none;
    box-shadow: 0 1px 6px rgba(32,33,36,.16);
}
.search-input:focus { box-shadow: 0 1px 8px rgba(66,133,244,.35); }
button, .button {
    border: 1px solid #dadce0; border-radius: 6px; padding: 10px 16px;
    background: #f8f9fa; color: #3c4043; cursor: pointer; text-decoration: none;
}
button:hover, .button:hover { background: #f1f3f4; }
.home {
    min-height: 100vh; display: flex; flex-direction: column;
    align-items: center; justify-content: center; padding: 70px 18px;
}
.home .buttons { margin-top: 20px; }
.header {
    display: flex; align-items: center; flex-wrap: wrap; gap: 22px;
    padding: 42px 22px 18px; border-bottom: 1px solid #eee;
}
.header .logo { font-size: 34px; margin: 0; letter-spacing: -2px; }
.header .search-form { width: min(70vw, 560px); }
.results { max-width: 720px; padding: 22px; }
.result-item { margin: 0 0 25px; }
.result-url { color: #5f6368; font-size: 13px; overflow-wrap: anywhere; }
.result-title { display: block; margin-top: 4px; color: #1a0dab; font-size: 19px; text-decoration: none; }
.result-title:hover { text-decoration: underline; }
.result-snippet { margin-top: 5px; color: #4d5156; font-size: 14px; line-height: 1.5; }
.muted { color: #70757a; font-size: 13px; }
.message { max-width: 680px; margin: 12vh auto; padding: 30px 22px; text-align: center; }
.message h1 { font-size: clamp(28px, 6vw, 48px); }
.message p { line-height: 1.6; }
.message .emoji { font-size: 64px; }
.error { color: #b3261e; }
.matrix {
    min-height: 100vh; background: #050805; color: #47ff75;
    font-family: monospace; padding: 10vh 8vw; overflow: hidden;
}
.matrix pre { white-space: pre-wrap; line-height: 1.7; font-size: clamp(12px, 2vw, 18px); }
.hacker {
    min-height: 100vh; background: #080808; color: #42ff62;
    font-family: monospace; padding: 10vh 8vw;
}
.hacker h1 { color: #ff4545; }
.explode { animation: shake .12s infinite; }
@keyframes shake {
    0% { transform: translate(0,0) rotate(0); }
    25% { transform: translate(3px,-2px) rotate(.3deg); }
    50% { transform: translate(-3px,2px) rotate(-.3deg); }
    75% { transform: translate(2px,3px) rotate(.2deg); }
    100% { transform: translate(-2px,-3px) rotate(0); }
}
@media (max-width: 600px) {
    .logo { font-size: 62px; }
    .header { gap: 12px; padding-top: 55px; }
    .header .search-form { width: 100%; }
    .creator { font-size: 12px; }
}
"""

HOME_TEMPLATE = """
<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fauxgle - Recherche Web</title><style>{{ style|safe }}</style></head>
<body><div class="creator">créé par Léo Oboda</div>
<main class="home">
  <div class="logo" aria-label="Fauxgle"><span>F</span><span>a</span><span>u</span><span>x</span><span>g</span><span>le</span></div>
  <form class="search-form" action="/search" method="get">
    <input class="search-input" type="text" name="q" maxlength="200"
      placeholder="Rechercher sur Fauxgle..." aria-label="Recherche" required>
    <button type="submit">Chercher</button>
  </form>
  <div class="buttons"><p class="muted">Essaie de trouver les commandes secrètes 👀</p></div>
</main></body></html>
"""

RESULTS_TEMPLATE = """
<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ query }} - Fauxgle</title><style>{{ style|safe }}</style></head>
<body><div class="creator">créé par Léo Oboda</div>
<header class="header">
  <a href="/" class="logo" aria-label="Retour à l'accueil" style="text-decoration:none">
    <span>F</span><span>a</span><span>u</span><span>x</span><span>g</span><span>le</span>
  </a>
  <form class="search-form" action="/search" method="get">
    <input class="search-input" type="text" name="q" maxlength="200"
      value="{{ query }}" aria-label="Recherche" required>
    <button type="submit">Chercher</button>
  </form>
</header>
<main class="results">
{% if error %}<p class="error">{{ error }}</p>
{% else %}
<p class="muted">{{ results|length }} résultat(s) trouvé(s) sur le web</p>
{% for item in results %}
<article class="result-item">
  <div class="result-url">{{ item.href }}</div>
  <a class="result-title" href="{{ item.href }}" target="_blank"
     rel="noopener noreferrer">{{ item.title }}</a>
  <div class="result-snippet">{{ item.body }}</div>
</article>
{% else %}
<p>Aucun résultat trouvé. Même Fauxgle a ses limites 😅</p>
{% endfor %}
{% endif %}
</main></body></html>
"""

MESSAGE_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} - Fauxgle</title><style>{{ style|safe }}</style></head>
<body class="{{ body_class }}"><div class="creator">créé par Léo Oboda</div>
<main class="message">
  <div class="emoji">{{ emoji }}</div>
  <h1>{{ heading }}</h1>
  <p>{{ message }}</p>
  <p><a class="button" href="/">Retour à Fauxgle</a></p>
</main></body></html>
"""

NOT_FOUND_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>404 Not Found</title><style>{{ style|safe }}</style></head>
<body><main class="message"><h1>404 Not Found</h1>
<p>Oups ! Cette recherche est introuvable sur Fauxgle. 😂</p>
<a class="button" href="/">Retour à Fauxgle</a></main></body></html>
"""

MATRIX_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fauxgle Matrix</title><style>{{ style|safe }}</style></head>
<body class="matrix"><h1>WAKE UP, LÉO...</h1>
<pre>
01000110 01000001 01010101 01011000 01000111 01001100 01000101
> connexion à la matrice...
> réalité chargée à 67%
> recherche de Neo... échec
> Fauxgle contrôle désormais la recherche. 👾
</pre><a class="button" href="/">Revenir à la réalité</a></body></html>
"""

HACKER_TEMPLATE = """
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulation de piratage</title><style>{{ style|safe }}</style></head>
<body class="hacker"><h1>⚠ SIMULATION DE PIRATAGE ⚠</h1>
<p>[ OK ] Initialisation du faux terminal...</p>
<p>[ OK ] Recherche de la base secrète de Fauxgle...</p>
<p>[ OK ] Accès refusé par le grille-pain.</p>
<p>[ LOL ] Ceci est une blague : aucun piratage n'a eu lieu.</p>
<a class="button" href="/">Quitter le terminal</a></body></html>
"""

EASTER_EGGS = {
    'bing': ('🦆', 'Bing ?', "Ici, c'est Fauxgle. On ne parle pas des concurrents."),
    'internet': ('🌐', 'Tu es déjà dessus !', 'Bienvenue sur Internet, version Fauxgle.'),
    'wifi': ('📶', 'Signal introuvable', 'As-tu essayé de rapprocher ton ordinateur de la box ?'),
    'mot de passe': ('🔑', 'Mot de passe refusé', 'Essaie plutôt de trouver un autre Easter Egg.'),
    'python': ('🐍', 'Python détecté !', 'Attention, ce serpent sait coder.'),
    'flask': ('🧪', 'Une petite bouteille de Flask ?', 'Fauxgle tourne grâce à Python et Flask !'),
    'html': ('🏗️', 'La structure du web', 'Sans HTML, Fauxgle serait juste une idée.'),
    'css': ('🎨', 'Un peu de style !', 'Le CSS rend Fauxgle beau, même en 404.'),
    'javascript': ('⚡', 'JavaScript activé', 'Promis, on ne va pas faire clignoter toute la page.'),
    'bug': ('🐛', 'Un bug ? Où ça ?', "Il s'est enfui dès qu'il a vu le développeur."),
    'virus': ('🦠', 'Alerte antivirus', 'Aucun virus détecté. Juste une blague de Fauxgle.'),
    'linux': ('🐧', 'Tux approuve', 'sudo apt install chocolat'),
    'windows': ('🪟', 'Fenêtre ouverte', 'Erreur : trop de fenêtres ouvertes.'),
    'mac': ('🍎', 'Une pomme par jour', 'Pas besoin de la croquer pour utiliser Fauxgle.'),
    'ordinateur': ('🖥️', 'Bip boop', 'Votre ordinateur est officiellement un ordinateur.'),
    'robot': ('🤖', 'Bip boup', 'Je suis un robot. Enfin... presque.'),
    'ia': ('🧠', 'Intelligence artificielle', 'Fauxgle réfléchit très fort. Il cherche encore.'),
    'code': ('⌨️', 'Code secret', '01000110 01100001 01110101 01111000 01100111 01101100 01100101'),
    'easter egg': ('🥚', 'Tu as trouvé un Easter Egg !', 'Mais celui-ci est caché à la vue de tous.'),
    'oeuf': ('🥚', "C'est pas Pâques ?", "Un œuf s'est glissé dans le moteur."),
    'bonjour': ('👋', 'BONJOUUUUR !', "Toute l'équipe de Fauxgle te souhaite une excellente journée."),
    'salut': ('😎', 'Yo !', "Alors, qu'est-ce qu'on cherche aujourd'hui ?"),
    'merci': ('💛', 'Avec plaisir !', 'Reviens quand tu veux sur Fauxgle.'),
    'au revoir': ('👋', 'À la prochaine !', 'Fauxgle gardera ta place au chaud.'),
    "je m'ennuie": ('🎲', 'Mission anti-ennui', "Trouve cinq autres Easter Eggs sans demander d'indice."),
    'aide': ('🆘', "Besoin d'aide ?", 'Essaie matrix, python, pizza, 42 ou Chuck Norris.'),
    'aide moi': ('🛟', 'Fauxgle à la rescousse', 'Premier conseil : ne tape surtout pas Google. 😏'),
    'qui suis je': ('🪞', 'Bonne question...', 'Tu es la personne qui vient de taper cette recherche.'),
    'la vie': ('🌱', 'La vie est belle', 'Surtout quand le Wi-Fi fonctionne.'),
    'amour': ('❤️', "L'amour est dans la barre de recherche", 'Même les algorithmes ont un petit cœur.'),
    'licorne': ('🦄', 'Licorne détectée', 'Elle est partie chercher un arc-en-ciel.'),
    'chat': ('🐱', 'Miaou !', 'Le chat a marché sur le clavier.'),
    'chien': ('🐶', 'Wouf !', 'Le chien de Fauxgle a trouvé un os.'),
    'dinosaure': ('🦖', 'ROAAAAR !', 'Ce dinosaure est plus vieux que les moteurs de recherche.'),
    'espace': ('🚀', "Vers l'infini et au-delà !", 'Fauxgle prépare une recherche sur Mars.'),
    'lune': ('🌙', 'Bonsoir la Lune', 'La lune te fait coucou.'),
    'soleil': ('☀️', 'Coup de soleil !', 'Pense à mettre de la crème solaire.'),
    'mer': ('🌊', 'Vague de résultats', 'Attention aux éclaboussures sur ton clavier.'),
    'fantome': ('👻', 'BOUH !', 'Tu as trouvé un résultat fantôme.'),
    'zombie': ('🧟', 'Cerveeeaaaau...', 'Le zombie voulait chercher un cerveau.'),
    'ninja': ('🥷', 'Recherche furtive', 'Le ninja a disparu avant même que la page charge.'),
    'pirate': ('🏴\u200d☠️', "À l'abordage !", 'Le trésor est caché quelque part dans le code.'),
    'tresor': ('💎', 'Trésor trouvé !', "Le vrai trésor, c'est le code qui fonctionne."),
    'argent': ('💸', 'Solde : 0 sourire perdu', 'Fauxgle est gratuit. Garde tes pièces pour les bonbons.'),
    'banane': ('🍌', 'Banane glissante', 'Attention, risque de chute de développeur.'),
    'fromage': ('🧀', 'Cheese !', 'Un résultat qui sent bon la France.'),
    'frites': ('🍟', 'Petite faim ?', 'Fauxgle recommande une pause goûter.'),
    'kebab': ('🥙', 'Kebab trouvé', 'La meilleure recherche à faire après minuit ?'),
    'chocolat': ('🍫', 'Chocolat virtuel', 'Malheureusement, ton écran ne se mange pas.'),
    'cafe': ('☕', 'Mode développeur activé', 'Un café, deux cafés... et encore quelques lignes de Python.'),
    'dodo': ('😴', "Il est l'heure de dormir", 'Même les serveurs ont besoin de repos.'),
    'musique': ('🎵', 'Fauxgle FM', 'La playlist du jour : bip, boup et musique de victoire.'),
    'danse': ('🕺', 'Petit pas de danse', 'Fauxgle danse uniquement en HTML.'),
    'football': ('⚽', 'GOOOOAL !', 'Le ballon est dans les filets. Recherche validée.'),
    'gaming': ('🎮', 'Mode gamer', 'Achievement débloqué : tu as trouvé un Easter Egg.'),
    'minecraft': ('⛏️', 'Creeper derrière toi !', 'Pssss... BOUM ! Heureusement, ton PC va bien.'),
    'roblox': ('🧱', 'Bienvenue dans le jeu', 'Fauxgle vient de gagner 0 Robux et beaucoup de style.'),
    'pokemon': ('⚡', 'Pikachu, à toi !', "Fauxgle utilise Recherche. C'est super efficace !"),
    'sonic': ('💨', 'Trop rapide !', 'Sonic a terminé la recherche avant toi.'),
    'mario': ('🍄', "It's-a me, Fauxgle !", 'Tu as trouvé un champignon numérique.'),
    'zelda': ('🗡️', 'Une quête commence', 'Ton prochain objectif : découvrir tous les secrets.'),
    'spiderman': ('🕷️', 'Un grand pouvoir...', '...implique une grande responsabilité de développeur.'),
    'star wars': ('🌌', 'Que la Force soit avec toi', 'Fauxgle, je suis ton moteur de recherche.'),
    'harry potter': ('⚡', 'Wingardium Recherchiosa !', 'Tu viens de lancer un sort de recherche.'),
    'minion': ('🍌', 'BANANAAAA !', 'Les Minions ont pris le contrôle de la barre.'),
    '67': ('🗣️', 'SIX SEVEN !', '33 + 33 + 1 = 67. Fauxgle connaît ses classiques.'),
    'six seven': ('🗣️', 'SIX SEVEN !', '33 + 33 + 1 = 67. Le moteur est dans le rythme.'),
    'tati krouty': ('🎤', 'TATI KROUTY !', "Le son est lancé dans la tête. Impossible de l'arrêter."),
    'nord': ('🥶', 'Bienvenue dans le Nord !', "Ici, même les recherches ont besoin d'une écharpe."),
    'france': ('🇫🇷', 'Cocorico !', 'Fauxgle est prêt pour une recherche à la française.'),
    'paris': ('🗼', 'Paris dans la place !', 'La Tour Eiffel vient de faire une recherche.'),
    'vacances': ('🏖️', 'Mode vacances', 'Tu es déjà à la plage dans ta tête.'),
    'anniversaire': ('🎂', 'Joyeux anniversaire !', "Fauxgle t'offre un gâteau imaginaire."),
    'noel': ('🎅', 'Ho ho ho !', 'Le Père Noël a mis Fauxgle dans ses favoris.'),
    'halloween': ('🎃', 'Des bonbons ou un sort !', 'Un fantôme vient de chercher des bonbons.'),
    'poisson d avril': ('🐟', "POISSON D'AVRIL !", 'Un poisson numérique vient de te piéger.'),
    'menteur': ('🤥', 'Moi ? Jamais !', 'Cette phrase est fausse. Ou peut-être pas.'),
    'test': ('🧪', 'Test réussi !', 'Si tu lis ça, la recherche fonctionne.'),
    'coucou': ('👋', 'Coucou toi !', 'Tu viens de débloquer un petit sourire.'),
    'lol': ('😂', 'LOL', 'Fauxgle a essayé de rire. Ha. Ha. Ha.'),
    'mdr': ('🤣', 'Mort de rire', 'Le serveur a failli tomber de sa chaise.'),
    'bravo': ('🏆', 'Bien joué !', 'Tu as le niveau pour devenir testeur officiel de Fauxgle.'),
    'leo oboda': ('👑', 'LE PATRON EN PERSONNE !', 'Fauxgle a été créé par Léo. Respect au développeur !'),
    'google chrome': ('🌐', 'Chrome détecté', 'Tu utilises un navigateur pour chercher un navigateur ?'),
    'firefox': ('🦊', 'Renard de feu', 'Le renard a volé les cookies. Pas ceux au chocolat.'),
    'edge': ('📐', 'Au bord du web', 'Tu es à la limite... de trouver un Easter Egg.'),
    'youtube': ('▶️', 'Pop-corn prêt ?', "La vidéo n'est pas disponible, mais l'imagination oui."),
    'tiktok': ('📱', 'Scroll infini', 'Tu es venu chercher une réponse et tu repars avec une danse.'),
    'instagram': ('📸', 'Cheese !', "N'oublie pas le filtre avant de poster."),
    'discord': ('🎧', 'Connexion au salon', 'Le salon Fauxgle est... imaginaire pour le moment.'),
    'fortnite': ('🪂', 'Top 1 ?', 'Fauxgle vient de construire un mur en carton.'),
    'among us': ('🚨', 'Un imposteur parmi nous', "C'était le moteur de recherche depuis le début."),
    'amongus': ('🚨', 'Un imposteur parmi nous', "C'était le moteur de recherche depuis le début."),
    'tetris': ('🟦', 'Ligne supprimée !', 'Tu viens de faire disparaître une ligne de bugs.'),
    'pacman': ('🟡', 'Waka waka !', 'Pac-Man a mangé tous les cookies.'),
    'pokemon go': ('📍', 'Un Pokémon sauvage apparaît', "Il s'est caché derrière le serveur."),
    'voiture': ('🚗', 'Vroum vroum', 'Recherche en première vitesse.'),
    'velo': ('🚲', 'À bicyclette', 'Pense à mettre un casque, même pour une recherche.'),
    'train': ('🚆', 'Le train entre en gare', 'Destination : la page des résultats.'),
    'avion': ('✈️', 'Décollage imminent', 'Attache ta ceinture, on part chercher.'),
    'dragon': ('🐉', 'Dragon détecté', 'Ne lui donne pas ton mot de passe.'),
    'requin': ('🦈', 'Attention aux dents', 'Ce résultat mord un peu.'),
    'pingouin': ('🐧', 'Copain de Tux', 'Les pingouins ont pris le contrôle du serveur.'),
    'panda': ('🐼', 'Mode bambou', 'Le panda a trouvé des résultats... en mangeant.'),
    'koala': ('🐨', 'Pause eucalyptus', 'Fais comme le koala : prends une pause.'),
    'girafe': ('🦒', 'Recherche en hauteur', 'Résultats visibles à plusieurs mètres.'),
    'elephant': ('🐘', "Mémoire d'éléphant", "Fauxgle n'oublie pas ses Easter Eggs."),
    'arc en ciel': ('🌈', 'Couleurs détectées', "Quelque part, un pot d'or attend."),
    'magie': ('✨', 'Abracadabra !', 'Un résultat est apparu par magie.'),
    'temps': ('⏳', 'Le temps passe', 'Cette recherche a pris... presque une seconde.'),
    'bonjour fauxgle': ('🎉', 'Bienvenue chez toi !', 'Le moteur te souhaite la bienvenue.'),
    'meilleur site': ('🏅', 'Fauxgle évidemment !', 'Réponse totalement impartiale. Signé : Fauxgle.'),
    'nul': ('🙃', 'Aïe, ça pique !', 'Le développeur va faire semblant de ne pas avoir vu ça.'),
    'je suis le boss': ('😎', 'On a trouvé le patron', 'Mais Léo reste le grand chef de Fauxgle.'),
}

def render_message(title, emoji, heading, message, body_class=""):
    return render_template_string(
        MESSAGE_TEMPLATE, style=BASE_STYLE, title=title, emoji=emoji,
        heading=heading, message=message, body_class=body_class
    )

def check_rate_limit():
    """Limite les recherches répétées depuis une même adresse IP."""
    now = time.monotonic()
    ip = request.remote_addr or "unknown"
    history = _requests_by_ip[ip]
    while history and now - history[0] > RATE_LIMIT_WINDOW_SECONDS:
        history.popleft()
    if len(history) >= RATE_LIMIT_REQUESTS:
        return False
    history.append(now)
    return True

def is_safe_result_url(value):
    """N'autorise que les liens web HTTP(S) dans les résultats externes."""
    try:
        parsed = urlparse(value or "")
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except (TypeError, ValueError):
        return False

@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
    )
    return response

@app.errorhandler(404)
def page_not_found(_error):
    return render_template_string(NOT_FOUND_TEMPLATE, style=BASE_STYLE), 404

@app.errorhandler(413)
def too_large(_error):
    return render_message("Recherche trop volumineuse", "📦", "Ouh là !", "La requête envoyée est trop volumineuse."), 413

@app.route("/")
def home():
    return render_template_string(HOME_TEMPLATE, style=BASE_STYLE)

@app.route("/search")
def search():
    query = request.args.get("q", "").strip()

    if len(query) > MAX_QUERY_LENGTH:
        return render_message(
            "Recherche trop longue", "✂️", "C'est beaucoup trop long !",
            f"Ta recherche doit faire {MAX_QUERY_LENGTH} caractères maximum."
        ), 400

    if not query:
        return render_template_string(HOME_TEMPLATE, style=BASE_STYLE)

    normalized = " ".join(query.casefold().split())

    # Easter eggs spéciaux
    if normalized == "google":
        return render_template_string(NOT_FOUND_TEMPLATE, style=BASE_STYLE), 404
    if normalized == "hacker":
        return render_template_string(HACKER_TEMPLATE, style=BASE_STYLE)
    if normalized == "matrix":
        return render_template_string(MATRIX_TEMPLATE, style=BASE_STYLE)
    if normalized == "admin":
        return render_message(
            "Accès refusé", "🚫", "ACCÈS REFUSÉ",
            "Tu n'es pas l'administrateur... enfin, sauf si tu es Léo 😎"
        ), 403
    if normalized == "explode":
        return render_message(
            "Autodestruction", "💥", "3... 2... 1... BOUM !",
            "Rassure-toi, Fauxgle va très bien. C'était juste un effet spécial.",
            "explode"
        )
    if normalized == "secret":
        return render_message(
            "Secret", "🔐", "Mot de passe mystérieux",
            "Indice : tape le prénom du créateur en minuscules."
        )
    if normalized == "leo":
        return render_message(
            "Le créateur", "👑", "LE CRÉATEUR EST DANS LA PLACE !",
            "Respect au patron de Fauxgle : Léo Oboda."
        )
    if normalized == "sudo leo":
        return render_message(
            "Mode patron", "👑", "Bienvenue, grand patron !",
            "Accès royal accordé. Longue vie à Fauxgle."
        )
    if normalized in EASTER_EGGS:
        emoji, heading, message = EASTER_EGGS[normalized]
        return render_message(query, emoji, heading, message)

    if not check_rate_limit():
        response = render_message(
            "Trop de recherches", "🐢", "Doucement !",
            "Tu fais trop de recherches. Attends une minute avant de réessayer."
        )
        return response, 429

    results = []
    error = None
    try:
        with DDGS() as ddgs:
            raw_results = ddgs.text(query, region="fr-fr", max_results=10)
            for item in raw_results:
                href = item.get("href", "")
                if not is_safe_result_url(href):
                    continue
                results.append({
                    "href": href,
                    "title": str(item.get("title", "Résultat sans titre"))[:500],
                    "body": str(item.get("body", ""))[:1500],
                })
    except Exception:
        logger.exception("Échec de la recherche DuckDuckGo")
        error = "Impossible de récupérer les résultats pour le moment. Réessaie plus tard."

    return render_template_string(
        RESULTS_TEMPLATE, style=BASE_STYLE, query=query,
        results=results, error=error
    )

if __name__ == "__main__":
    # En production, lance plutôt Gunicorn (ex. : gunicorn app:app).
    app.run(host="0.0.0.0", port=5000, debug=False)
