from flask import Flask, request, jsonify, send_from_directory, abort
import pandas as pd
import os
import re

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def slugify(name):
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug).strip("-")
    return slug


def parse_admissions_factors(value):
    factors = {}
    for pair in value.split("|"):
        factor, _, rating = pair.partition(":")
        factors[factor.strip()] = rating.strip()
    return factors


colleges_df = pd.read_csv(os.path.join(BASE_DIR, "colleges.csv"))
colleges_df["majors_list"] = colleges_df["majors"].str.split(",")
colleges_df["slug"] = colleges_df["name"].apply(slugify)
colleges_df["admissions_factors_dict"] = colleges_df["admissions_factors"].apply(parse_admissions_factors)
colleges_df = colleges_df.sort_values("min_gpa", ascending=False).reset_index(drop=True)

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

    major = data.get("major", "").strip()
    location = data.get("location", "Any").strip()

    if not (0.0 <= gpa <= 4.0):
        return jsonify({"error": "GPA must be between 0.0 and 4.0"}), 400

    results = colleges_df[colleges_df["min_gpa"] <= gpa].copy()

    if location and location != "Any":
        results = results[results["location"] == location]

    if major:
        results = results[
            results["majors_list"].apply(
                lambda majors: any(major.lower() in m.lower() for m in majors)
            )
        ]

    matches = results[["name", "slug", "location", "min_gpa", "majors", "type"]].to_dict(
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
        "min_gpa": college["min_gpa"],
        "majors": college["majors_list"],
        "type": college["type"],
        "admissions_factors": college["admissions_factors_dict"],
    })


@app.route("/api/options")
def get_options():
    all_majors = set()
    for majors in colleges_df["majors_list"]:
        all_majors.update(m.strip() for m in majors)
    return jsonify({"locations": LOCATIONS, "majors": sorted(all_majors)})


if __name__ == "__main__":
    app.run(debug=True, port=8080)
