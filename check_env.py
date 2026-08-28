import os
import sys

from dotenv import load_dotenv

load_dotenv(override=True)

REQUIRED = ["GOOGLE_API_KEY"]
MODEL = os.getenv("EVAL_MODEL", "gemini-3.6-flash")


def check_env_vars():
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        print(f"[FAIL] Missing environment variable(s): {', '.join(missing)}")
        print("       Add them to your .env file (see README).")
        return False
    print(f"[OK]   GOOGLE_API_KEY is set ({len(os.getenv('GOOGLE_API_KEY'))} chars).")
    return True


def check_model():
    try:
        from google import genai
    except ImportError:
        print("[FAIL] google-genai is not installed. Run: pip install google-adk")
        return False

    key = os.getenv("GOOGLE_API_KEY")
    print(f"[..]   Calling model '{MODEL}' ...")
    try:
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(model=MODEL, contents="Reply with the single word: OK")
        text = (resp.text or "").strip()
        if text:
            print(f"[OK]   Model responded: {text!r}")
            return True
        print("[FAIL] Model returned an empty response.")
        return False
    except Exception as e:
        print(f"[FAIL] Model call failed: {type(e).__name__}: {e}")
        return False


def main():
    print("=== AI Research Coach: environment check ===")
    ok = True
    ok &= check_env_vars()
    if ok:
        ok &= check_model()
    print("=== " + ("ALL GOOD" if ok else "CHECK FAILED") + " ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
