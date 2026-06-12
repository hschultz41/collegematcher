from flask import Flask, request, jsonify, send_from_directory, abort
import pandas as pd
import os
import random
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


# Relative weight given to each Common Data Set importance level when computing match scores.
FACTOR_WEIGHTS = {"VI": 3, "I": 2, "C": 1, "NC": 0}

CLASS_RANK_SCORES = {
    "Top 10%": 100,
    "Top 25%": 80,
    "Top 50%": 60,
    "Bottom 50%": 30,
    "Not ranked": 50,
}

# Tier 1 = most impressive (national/international level), Tier 4 = least.
EXTRACURRICULAR_TIER_SCORES = {
    "Tier 1": 100,
    "Tier 2": 80,
    "Tier 3": 60,
    "Tier 4": 40,
}

# Admissions readers evaluate rigor "in context" of what a student's school offers.
# Students from under-resourced schools get credit for maximizing what was available to them.
HIGH_SCHOOL_CONTEXT_BONUS = {
    "Highly Selective / Feeder School": 0,
    "Competitive Private School": 0,
    "Conventional Public School": 0,
    "Rural / Small Public School": 15,
    "Underserved / Title I School": 15,
    "Homeschool / Online School": 0,
}


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_match_score(college, profile):
    weighted_total = 0
    weight_sum = 0

    gpa = _to_float(profile.get("gpa"))
    if gpa is not None:
        if gpa > college["gpa_75"]:
            subscore = 100
        elif gpa >= college["gpa_25"]:
            subscore = 75
        else:
            subscore = 40
        weight = FACTOR_WEIGHTS.get(college["gpa_rating"], 0)
        weighted_total += weight * subscore
        weight_sum += weight

    test_score = _to_float(profile.get("testScore"))
    test_type = profile.get("testType")
    if test_score is not None and test_type in ("SAT", "ACT"):
        if test_type == "SAT":
            score_25, score_75 = college["sat_25"], college["sat_75"]
        else:
            score_25, score_75 = college["act_25"], college["act_75"]
        if test_score > score_75:
            subscore = 100
        elif test_score >= score_25:
            subscore = 75
        else:
            subscore = 40
        weight = FACTOR_WEIGHTS.get(college["test_scores_rating"], 0)
        weighted_total += weight * subscore
        weight_sum += weight

    class_rank = profile.get("classRank")
    if class_rank in CLASS_RANK_SCORES:
        subscore = CLASS_RANK_SCORES[class_rank]
        weight = FACTOR_WEIGHTS.get(college["class_rank_rating"], 0)
        weighted_total += weight * subscore
        weight_sum += weight

    extracurricular_tier = profile.get("extracurriculars")
    if extracurricular_tier in EXTRACURRICULAR_TIER_SCORES:
        subscore = EXTRACURRICULAR_TIER_SCORES[extracurricular_tier]
        weight = FACTOR_WEIGHTS.get(college["extracurriculars_rating"], 0)
        weighted_total += weight * subscore
        weight_sum += weight

    rigor_courses = _to_float(profile.get("rigorCourses"))
    if rigor_courses is not None:
        rigor_offered = _to_float(profile.get("rigorOffered"))
        if rigor_offered:
            subscore = (rigor_courses / rigor_offered) * 100
        else:
            subscore = rigor_courses * 10
        subscore += HIGH_SCHOOL_CONTEXT_BONUS.get(profile.get("highSchoolType"), 0)
        subscore = max(0, min(100, subscore))
        weight = FACTOR_WEIGHTS.get(college["rigor_rating"], 0)
        weighted_total += weight * subscore
        weight_sum += weight

    if weight_sum == 0:
        return None
    return round(weighted_total / weight_sum)


# Tier-adjusted thresholds for classifying a school as a Hard Reach, Reach, Target, or Safety.
# More selective tiers get a larger penalty since elite schools remain a "Reach"
# for nearly everyone regardless of stats.
TIER_PENALTY = {1: 60, 2: 45, 3: 30, 4: 15, 5: 0, 6: 0}


def classify_application_category(college, match_score):
    if match_score is None:
        return None

    tier = int(college["tier"])
    adjusted_score = match_score - TIER_PENALTY.get(tier, 30)

    if adjusted_score >= 75:
        category = "Safety"
    elif adjusted_score >= 50:
        category = "Target"
    elif adjusted_score >= 20:
        category = "Reach"
    else:
        category = "Hard Reach"

    # The most selective schools (Tier 1-2) are never a Target or Safety,
    # no matter how strong a student's stats are.
    if tier <= 2 and category in ("Safety", "Target"):
        category = "Reach"

    return category


# Columns returned for each school in a recommendations list.
RECOMMENDATION_COLUMNS = ["name", "slug", "location", "gpa_25", "gpa_75", "type", "match_score", "application_category"]


def build_recommendation_lists(results):
    """Pick the highest-scoring schools for each application category.

    If a category doesn't have enough schools, its remaining slots are
    filled from the next "harder" category (e.g. Target -> Reach -> Hard Reach),
    so a student is never recommended a Target/Safety school they can't realistically get.
    """
    used_slugs = set()

    def take(categories, count):
        selected = []
        for category in categories:
            if len(selected) >= count:
                break
            pool = results[
                (results["application_category"] == category) & (~results["slug"].isin(used_slugs))
            ]
            if category in ("Target", "Safety"):
                # Within Target/Safety, prefer the least-selective (highest tier number)
                # schools first -- these are the "safest" picks in that category.
                pool = pool.sort_values(["tier", "match_score"], ascending=[False, False])
            else:
                pool = pool.sort_values("match_score", ascending=False)
            chosen = pool.head(count - len(selected))
            selected.extend(chosen[RECOMMENDATION_COLUMNS].to_dict(orient="records"))
            used_slugs.update(chosen["slug"])
        return selected

    reaches = take(["Reach", "Hard Reach"], 10)
    targets = take(["Target", "Reach", "Hard Reach"], 7)
    safeties = take(["Safety", "Target", "Reach", "Hard Reach"], 3)
    return reaches, targets, safeties


# Placeholder decision odds per application category, used only by the decision simulator.
DECISION_WEIGHTS = {
    "Safety": {"Accepted": 80, "Waitlisted": 15, "Rejected": 5},
    "Target": {"Accepted": 50, "Waitlisted": 25, "Rejected": 25},
    "Reach": {"Accepted": 20, "Waitlisted": 25, "Rejected": 55},
    "Hard Reach": {"Accepted": 8, "Waitlisted": 12, "Rejected": 80},
}


def simulate_decision(category):
    weights = DECISION_WEIGHTS.get(category, DECISION_WEIGHTS["Target"])
    outcomes, odds = zip(*weights.items())
    return random.choices(outcomes, weights=odds, k=1)[0]


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

    profile = {**data, "gpa": gpa}
    results["match_score"] = results.apply(lambda college: compute_match_score(college, profile), axis=1)
    results["application_category"] = results.apply(
        lambda college: classify_application_category(college, college["match_score"]), axis=1
    )
    results = results.sort_values("match_score", ascending=False)

    matches = results[
        ["name", "slug", "location", "gpa_25", "gpa_75", "type", "match_score", "application_category"]
    ].to_dict(orient="records")
    return jsonify({"matches": matches, "total": len(matches)})


@app.route("/api/recommendations", methods=["POST"])
def recommendations():
    data = request.get_json() or {}

    location = (data.get("location") or "Any").strip()

    results = colleges_df.copy()
    if location and location != "Any":
        results = results[results["location"] == location]

    results["match_score"] = results.apply(lambda college: compute_match_score(college, data), axis=1)
    results = results.dropna(subset=["match_score"])

    if results.empty:
        return jsonify({"error": "Not enough profile information to generate recommendations."}), 400

    results["application_category"] = results.apply(
        lambda college: classify_application_category(college, college["match_score"]), axis=1
    )

    reaches, targets, safeties = build_recommendation_lists(results)
    return jsonify({"reaches": reaches, "targets": targets, "safeties": safeties})


@app.route("/recommendations")
def recommendations_page():
    return send_from_directory(BASE_DIR, "recommendations.html")


@app.route("/api/simulate", methods=["POST"])
def simulate():
    data = request.get_json() or {}

    location = (data.get("location") or "Any").strip()

    results = colleges_df.copy()
    if location and location != "Any":
        results = results[results["location"] == location]

    results["match_score"] = results.apply(lambda college: compute_match_score(college, data), axis=1)
    results = results.dropna(subset=["match_score"])

    if results.empty:
        return jsonify({"error": "Not enough profile information to simulate decisions."}), 400

    results["application_category"] = results.apply(
        lambda college: classify_application_category(college, college["match_score"]), axis=1
    )

    reaches, targets, safeties = build_recommendation_lists(results)
    for school in reaches + targets + safeties:
        school["decision"] = simulate_decision(school["application_category"])

    return jsonify({"reaches": reaches, "targets": targets, "safeties": safeties})


@app.route("/decisions")
def decisions_page():
    return send_from_directory(BASE_DIR, "decisions.html")


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
    profile = {
        "gpa": request.args.get("gpa"),
        "testType": request.args.get("testType"),
        "testScore": request.args.get("testScore"),
        "classRank": request.args.get("classRank"),
        "extracurriculars": request.args.get("extracurriculars"),
        "rigorCourses": request.args.get("rigorCourses"),
        "rigorOffered": request.args.get("rigorOffered"),
        "highSchoolType": request.args.get("highSchoolType"),
    }
    match_score = compute_match_score(college, profile)
    return jsonify({
        "name": college["name"],
        "slug": college["slug"],
        "location": college["location"],
        "gpa_25": college["gpa_25"],
        "gpa_75": college["gpa_75"],
        "sat_25": int(college["sat_25"]),
        "sat_75": int(college["sat_75"]),
        "act_25": int(college["act_25"]),
        "act_75": int(college["act_75"]),
        "test_optional": college["test_optional"] == "Yes",
        "type": college["type"],
        "admissions_factors": college["admissions_factors_dict"],
        "match_score": match_score,
        "application_category": classify_application_category(college, match_score),
    })


@app.route("/map")
def map_page():
    return send_from_directory(BASE_DIR, "map.html")


@app.route("/api/schools")
def schools():
    results = colleges_df.copy()

    profile = {
        "gpa": request.args.get("gpa"),
        "testType": request.args.get("testType"),
        "testScore": request.args.get("testScore"),
        "classRank": request.args.get("classRank"),
        "extracurriculars": request.args.get("extracurriculars"),
        "rigorCourses": request.args.get("rigorCourses"),
        "rigorOffered": request.args.get("rigorOffered"),
        "highSchoolType": request.args.get("highSchoolType"),
    }

    columns = ["name", "slug", "location", "type", "gpa_25", "gpa_75", "lat", "lng"]
    if any(profile.values()):
        results["match_score"] = results.apply(lambda college: compute_match_score(college, profile), axis=1)
        results["application_category"] = results.apply(
            lambda college: classify_application_category(college, college["match_score"]), axis=1
        )
        results["match_score"] = results["match_score"].astype(object).where(results["match_score"].notna(), None)
        columns += ["match_score", "application_category"]

    return jsonify({"schools": results[columns].to_dict(orient="records")})


@app.route("/api/options")
def get_options():
    return jsonify({"locations": LOCATIONS})


if __name__ == "__main__":
    app.run(debug=True, port=8080)
