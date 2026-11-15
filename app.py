from flask import Flask, render_template_string, request
from duckduckgo_search import DDGS

app = Flask(__name__)

# Template HTML pour la page d'accueil
HOME_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>Fauxgle - Recherche Web</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background: #fff;
        }

        .creator {
            position: fixed;
            top: 12px;
            left: 16px;
            font-size: 14px;
            color: #555;
        }

        .logo {
            font-size: 80px;
            font-weight: bold;
            margin-bottom: 20px;
        }

        .logo span:nth-child(1) { color: #4285F4; }
        .logo span:nth-child(2) { color: #EA4335; }
        .logo span:nth-child(3) { color: #FBBC05; }
        .logo span:nth-child(4) { color: #4285F4; }
        .logo span:nth-child(5) { color: #34A853; }
        .logo span:nth-child(6) { color: #EA4335; }

        form {
            width: 100%;
            max-width: 500px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        input[type="text"] {
            width: 100%;
            padding: 12px 20px;
            font-size: 16px;
            border: 1px solid #dfe1e5;
            border-radius: 24px;
            outline: none;
            box-shadow: 0 1px 6px rgba(32, 33, 36, 0.2);
        }

        .buttons {
            margin-top: 20px;
        }

        button {
            background-color: #f8f9fa;
            border: 1px solid #f8f9fa;
            border-radius: 4px;
            color: #3c4043;
            font-size: 14px;
            margin: 0 4px;
            padding: 10px 16px;
            cursor: pointer;
        }

        button:hover {
            border: 1px solid #dadce0;
            box-shadow: 0 1px 1px rgba(0, 0, 0, 0.1);
        }
    </style>
</head>
<body>
    <div class="creator">créé par Léo Oboda</div>

    <div class="logo">
        <span>F</span><span>a</span><span>u</span><span>x</span><span>g</span><span>le</span>
    </div>

    <form action="/search" method="get">
        <input
            type="text"
            name="q"
            placeholder="Rechercher sur Fauxgle..."
            required
        >
        <div class="buttons">
            <button type="submit">Recherche Fauxgle</button>
        </div>
    </form>
</body>
</html>
"""

# Template HTML pour la page de résultats
RESULTS_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>{{ query }} - Fauxgle</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
        }

        .creator {
            position: fixed;
            top: 12px;
            left: 16px;
            font-size: 14px;
            color: #555;
        }

        .header {
            display: flex;
            align-items: center;
            border-bottom: 1px solid #dfe1e5;
            padding: 35px 0 15px;
        }

        .logo {
            font-size: 24px;
            font-weight: bold;
            margin-right: 30px;
        }

        .logo span:nth-child(1) { color: #4285F4; }
        .logo span:nth-child(2) { color: #EA4335; }
        .logo span:nth-child(3) { color: #FBBC05; }
        .logo span:nth-child(4) { color: #4285F4; }
        .logo span:nth-child(5) { color: #34A853; }
        .logo span:nth-child(6) { color: #EA4335; }

        form {
            display: flex;
        }

        input[type="text"] {
            width: 400px;
            padding: 8px 15px;
            font-size: 14px;
            border: 1px solid #dfe1e5;
            border-radius: 24px;
            outline: none;
        }

        .results {
            margin-top: 20px;
            max-width: 650px;
        }

        .result-item {
            margin-bottom: 25px;
        }

        .result-url {
            font-size: 14px;
            color: #202124;
            word-break: break-all;
        }

        .result-title {
            font-size: 20px;
            color: #1a0dab;
            text-decoration: none;
            display: block;
            margin-top: 3px;
        }

        .result-title:hover {
            text-decoration: underline;
        }

        .result-snippet {
            font-size: 14px;
            color: #4d5156;
            margin-top: 4px;
            line-height: 1.4;
        }

        .error {
            color: #d93025;
        }
    </style>
</head>
<body>
    <div class="creator">créé par Léo Oboda</div>

    <div class="header">
        <div class="logo">
            <a href="/" style="text-decoration: none;">
                <span>F</span><span>a</span><span>u</span><span>x</span><span>g</span><span>le</span>
            </a>
        </div>

        <form action="/search" method="get">
            <input type="text" name="q" value="{{ query }}" required>
        </form>
    </div>

    <div class="results">
        {% if error %}
            <p class="error">{{ error }}</p>
        {% else %}
            <p style="color: #70757a; font-size: 14px;">
                {{ results|length }} résultats réels trouvés sur le web
            </p>

            {% for item in results %}
                <div class="result-item">
                    <div class="result-url">{{ item['href'] }}</div>
                    <a
                        href="{{ item['href'] }}"
                        target="_blank"
                        rel="noopener noreferrer"
                        class="result-title"
                    >{{ item['title'] }}</a>
                    <div class="result-snippet">{{ item['body'] }}</div>
                </div>
            {% endfor %}
        {% endif %}
    </div>
</body>
</html>
"""

# Page affichée quand la recherche est "google"
NOT_FOUND_TEMPLATE = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <title>404 Not Found</title>
</head>
<body>
    <h1>404 Not Found</h1>
</body>
</html>
"""


@app.route("/")
def home():
    return render_template_string(HOME_TEMPLATE)


@app.route("/search")
def search():
    query = request.args.get("q", "").strip()

    # Affiche une erreur 404 si la recherche est exactement "google"
    if query.casefold() == "google":
        return render_template_string(NOT_FOUND_TEMPLATE), 404

    results = []
    error = None

    if query:
        try:
            with DDGS() as ddgs:
                results = list(
                    ddgs.text(query, region="fr-fr", max_results=10)
                )
        except Exception as e:
            error = f"Erreur lors de la récupération des résultats : {e}"

    return render_template_string(
        RESULTS_TEMPLATE,
        query=query,
        results=results,
        error=error,
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
