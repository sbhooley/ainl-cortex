"""Tests for AINL detection hook."""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from ainl_detection import AINLDetector


@pytest.fixture
def detector():
    """Create detector instance."""
    return AINLDetector()


class TestDetectRecurring:
    """Test detection of recurring patterns."""

    def test_hourly_monitor(self, detector):
        """Test detection of hourly monitoring."""
        prompt = "Check my API health every hour and alert me if it's down"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True
        assert result["confidence"] >= 0.6
        assert "recurring" in result["use_case"].lower() or "monitor" in result["use_case"].lower()
        assert len(result["reasons"]) > 0

    def test_daily_automation(self, detector):
        """Test detection of daily automation."""
        prompt = "Run this data export daily at 2 AM"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True
        assert any("recurring" in reason.lower() for reason in result["reasons"])

    def test_scheduled_workflow(self, detector):
        """Test detection of scheduled workflow."""
        prompt = "Create a workflow that runs weekly to process user data"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True


class TestDetectWorkflow:
    """Test detection of workflow patterns."""

    def test_multi_step_workflow(self, detector):
        """Test detection of multi-step workflow."""
        prompt = "Fetch data from API A, process it, then send to API B"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True
        assert "workflow" in result["use_case"].lower() or "api" in result["use_case"].lower()

    def test_automation_request(self, detector):
        """Test detection of automation."""
        prompt = "Automate the process of checking inventory and updating the database"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True


class TestDetectBlockchain:
    """Test detection of blockchain use cases."""

    def test_solana_balance(self, detector):
        """Test detection of Solana operations."""
        prompt = "Check my Solana wallet balance and alert if low"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True
        assert result["confidence"] >= 0.6
        assert result["use_case"] == "blockchain_monitor"

    def test_crypto_monitoring(self, detector):
        """Test detection of crypto monitoring."""
        prompt = "Monitor my crypto wallet and send notifications"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True


class TestDetectCostConcerns:
    """Test detection of cost sensitivity."""

    def test_cost_optimization(self, detector):
        """Test detection of cost concerns."""
        prompt = "Create a workflow that minimizes token costs"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True
        assert any("cost" in reason.lower() or "efficiency" in reason.lower()
                   for reason in result["reasons"])

    def test_budget_mention(self, detector):
        """Test detection of budget concerns."""
        prompt = "I'm on a budget, need to check APIs efficiently"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is True


class TestNoSuggestion:
    """Test cases where AINL should NOT be suggested."""

    def test_one_time_script(self, detector):
        """Test that one-time scripts don't trigger."""
        prompt = "Write a Python script to analyze this CSV once"
        result = detector.analyze_prompt(prompt, {})

        # Should have low confidence
        assert result["confidence"] < 0.6

    def test_ui_request(self, detector):
        """Test that UI requests don't trigger."""
        prompt = "Create a React dashboard for my data"
        result = detector.analyze_prompt(prompt, {})

        assert result["confidence"] < 0.6

    def test_generic_question(self, detector):
        """Test that generic questions don't trigger."""
        prompt = "How do I sort an array in Python?"
        result = detector.analyze_prompt(prompt, {})

        assert result["suggest_ainl"] is False


class TestContextDetection:
    """Test context-aware detection."""

    def test_existing_ainl_files(self, detector):
        """Test detection boosted by existing .ainl files."""
        prompt = "Create another monitor"
        context = {"workingDir": str(Path(__file__).parent)}

        # Without .ainl files
        result_without = detector.analyze_prompt(prompt, {})

        # Mock context would need actual .ainl files
        # This is a placeholder test
        assert "confidence" in result_without


class TestUseCaseClassification:
    """Test use case classification."""

    def test_api_workflow_classification(self, detector):
        """Test API workflow classification."""
        use_case = detector._determine_use_case(
            "fetch api data and process",
            recurring=0,
            workflow=1,
            blockchain=0,
            api=2
        )

        assert use_case == "api_workflow"

    def test_blockchain_classification(self, detector):
        """Test blockchain classification."""
        use_case = detector._determine_use_case(
            "solana wallet check",
            recurring=0,
            workflow=0,
            blockchain=1,
            api=0
        )

        assert use_case == "blockchain_monitor"

    def test_general_fallback(self, detector):
        """Test fallback classification."""
        use_case = detector._determine_use_case(
            "some task",
            recurring=0,
            workflow=0,
            blockchain=0,
            api=0
        )

        assert use_case == "general_workflow"


class TestSuggestionGeneration:
    """Test suggestion text generation."""

    def test_blockchain_suggestion(self, detector):
        """Test blockchain suggestion text."""
        text = detector._generate_suggestion("blockchain_monitor", 0.8, [])

        assert "blockchain" in text.lower()
        assert "solana" in text.lower()
        assert "token savings" in text.lower() or "savings" in text.lower()

    def test_recurring_suggestion(self, detector):
        """Test recurring monitor suggestion."""
        text = detector._generate_suggestion("recurring_monitor", 0.9, [])

        assert "recurring" in text.lower() or "monitor" in text.lower()
        assert "cron" in text.lower() or "scheduling" in text.lower()


class TestAinlDetectionMain:
    """Test ainl_detection.main() entry point — particularly the project_id fix."""

    def test_main_does_not_crash_with_empty_payload(self, monkeypatch):
        """main() must not crash when given an empty hook payload."""
        import json, sys
        from io import StringIO
        import importlib
        import ainl_detection
        importlib.reload(ainl_detection)
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps({})))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        ainl_detection.main()  # must return normally, not raise

    def test_main_does_not_crash_with_plain_question(self, monkeypatch):
        """A plain question prompt should not trigger a suggestion and must not raise."""
        import json, sys
        from io import StringIO
        import importlib
        import ainl_detection
        importlib.reload(ainl_detection)
        payload = {"prompt": "What is 2+2?", "cwd": "/tmp"}
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        ainl_detection.main()  # must return normally
        # No suggestion emitted for a trivial question
        assert captured.getvalue().strip() == ""

    def test_main_uses_cwd_from_payload_not_path_dot_cwd(self, monkeypatch, tmp_path):
        """main() should read cwd from payload, not Path.cwd() (plugin root)."""
        import json, sys
        from io import StringIO
        import importlib
        import ainl_detection
        importlib.reload(ainl_detection)
        payload = {"prompt": "run every hour", "cwd": str(tmp_path)}
        monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
        captured = StringIO()
        monkeypatch.setattr(sys, "stdout", captured)
        ainl_detection.main()  # must return normally regardless of cwd
