from flask import Flask, request, jsonify, send_from_directory, abort
import pandas as pd
import os
import re

app = Flask(__name__)
app.json.sort_keys = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def slugify(name):
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug


# Maps each colleges.csv rating column to its Common Data Set Section C7 factor name.
# Ratings are stored as short codes (VI/I/C/NC) in the CSV for easy editing.
RATING_CODES = {"VI": "Very Important", "I": "Important", "C": "Considered", "NC": "Not Considered"}

FACTOR_COLUMNS = {
    "rigor_rating": "Rigor of secondary school record",
    "class_rank_rating": "Class rank",
    "gpa_rating": "Academic GPA",
    "test_scores_rating": "Standardized test scores",
    "essay_rating": "Application essay",
    "recommendations_rating": "Recommendations",
    "extracurriculars_rating": "Extracurricular activities",
    "character_rating": "Character/personal qualities",
}


def build_admissions_factors(row):
    return {
        factor_name: RATING_CODES.get(row[column], "Considered")
        for column, factor_name in FACTOR_COLUMNS.items()
    }


colleges_df = pd.read_csv(os.path.join(BASE_DIR, "colleges.csv"))
colleges_df["slug"] = colleges_df["name"].apply(slugify)
colleges_df["admissions_factors_dict"] = colleges_df.apply(build_admissions_factors, axis=1)
colleges_df = colleges_df.sort_values("gpa_25", ascending=False).reset_index(drop=True)

LOCATIONS = ["Any", "West", "Northeast", "Midwest", "Southeast", "South"]


@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/api/match", methods=["POST"])
def match_colleges():
    data = request.get_json()

    try:
        gpa = float(data.get("gpa", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid GPA"}), 400

    location = data.get("location", "Any").strip()

    if not (0.0 <= gpa <= 4.0):
        return jsonify({"error": "GPA must be between 0.0 and 4.0"}), 400

    results = colleges_df[colleges_df["gpa_25"] <= gpa].copy()

    if location and location != "Any":
        results = results[results["location"] == location]

    matches = results[["name", "slug", "location", "gpa_25", "gpa_75", "type"]].to_dict(
        orient="records"
    )
    return jsonify({"matches": matches, "total": len(matches)})


@app.route("/college/<slug>")
def college_page(slug):
    if slug not in colleges_df["slug"].values:
        abort(404)
    return send_from_directory(BASE_DIR, "college.html")


@app.route("/api/college/<slug>")
def college_detail(slug):
    match = colleges_df[colleges_df["slug"] == slug]
    if match.empty:
        return jsonify({"error": "College not found"}), 404

    college = match.iloc[0]
    return jsonify({
        "name": college["name"],
        "slug": college["slug"],
        "location": college["location"],
        "gpa_25": college["gpa_25"],
        "gpa_75": college["gpa_75"],
        "type": college["type"],
        "admissions_factors": college["admissions_factors_dict"],
    })


@app.route("/api/options")
def get_options():
    return jsonify({"locations": LOCATIONS})


if __name__ == "__main__":
    app.run(debug=True, port=8080)
