import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app import create_app
from services.ai_service import AIAnalysisError, _parse_json, analyze_complaint, validate_analysis

class AIServiceTests(unittest.TestCase):
    def test_valid_structured_response(self):
        result = validate_analysis({"category":"Delivery","sentiment":"Negative","priority":"High","summary":"Late order.","recommended_action":"Check tracking.","response":"We are sorry."})
        self.assertEqual(result["category"], "Delivery")

    def test_invalid_category_rejected(self):
        with self.assertRaises(AIAnalysisError): validate_analysis({"category":"Shipping","sentiment":"Negative","priority":"High","summary":"Late order.","recommended_action":"Check tracking.","response":"We are sorry."})

    def test_invalid_json_rejected(self):
        with self.assertRaises(AIAnalysisError): _parse_json("not json")

    def test_markdown_fenced_json_is_parsed(self):
        result = _parse_json('```json\n{"category":"Delivery"}\n```')
        self.assertEqual(result["category"], "Delivery")

    def test_json_with_preamble_and_trailing_text_is_parsed(self):
        result = _parse_json('Here is the result: {"category":"Delivery"} Done.')
        self.assertEqual(result["category"], "Delivery")

    def test_mock_mode_is_deterministic(self):
        app = create_app({"TESTING":True,"AI_MOCK_MODE":True})
        with app.app_context():
            result = analyze_complaint("My order delivery is late.")
            self.assertEqual(result["category"], "Delivery")
            self.assertTrue(result["response"])

    def test_groq_client_path_parses_structured_json(self):
        app = create_app({"TESTING":True,"AI_MOCK_MODE":False,"GROQ_API_KEY":"test-only-key","GROQ_MODEL":"qwen/qwen3.8-27b"})
        content = '{"category":"Delivery","sentiment":"Negative","priority":"High","summary":"Late order.","recommended_action":"Check tracking.","response":"We are sorry."}'
        completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: completion)))
        with app.app_context(), patch("groq.Groq", return_value=fake_client):
            result = analyze_complaint("My order is late.")
        self.assertEqual(result["priority"], "High")

if __name__ == "__main__": unittest.main()
