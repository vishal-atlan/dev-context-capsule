"""TF-IDF retrieval over stored capsules. Returns top-k most relevant."""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from capsule.memory.store import get_all_capsules


def search_capsules(query: str, repo_path: str = "", top_k: int = 5) -> str:
    capsules = get_all_capsules(repo_path=repo_path)
    if not capsules:
        return "No capsules found to search."

    # Build corpus from summary + branch name for better signal
    corpus = [f"{c['branch']} {c['summary']}" for c in capsules]

    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        tfidf_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query])
    except ValueError:
        return "Not enough capsule content to search yet."

    scores = cosine_similarity(query_vec, tfidf_matrix).flatten()
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    for i in top_indices:
        if scores[i] < 0.01:
            break
        c = capsules[i]
        results.append(f"[{c['id']}] score={scores[i]:.2f} | {c['branch']} @ {c['captured_at'][:16]}\n  {c['summary']}")

    return "\n\n".join(results) if results else "No relevant capsules found for that query."
