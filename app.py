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
    "chatgpt": ("🤖", "Même lui ne sait pas quoi chercher !", "Essaie une autre recherche, humain."),
    "chuck norris": ("🥋", "Chuck Norris a déjà trouvé ce que tu cherches.", "Il a même trouvé la page qui n'existe pas."),
    "42": ("🌌", "42", "La réponse à la vie, à l'univers et au reste."),
    "fauxgle": ("😂", "Tu cherches ton propre site ?", "Il est juste devant toi. Créé par Léo Oboda !"),
    "pizza": ("🍕", "Livraison impossible !", "Nous sommes un moteur de recherche, pas une pizzeria."),
    "404": ("🧱", "404ception !", "Tu as demandé une erreur 404... alors en voici une autre."),
    "leo": ("👑", "LE CRÉATEUR EST DANS LA PLACE !", "Respect au patron de Fauxgle : Léo Oboda."),
    "secret": ("🔐", "Mot de passe mystérieux", "Indice : le prénom du créateur, en minuscules."),
    "sudo leo": ("👑", "Bienvenue, grand patron !", "Accès royal accordé. Longue vie à Fauxgle."),
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
