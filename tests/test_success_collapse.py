# Synthelion — Python port of Caveman (https://github.com/francescopaolopassaro/caveman)
# © 2026 Passaro Francesco Paolo — Digitalsolutions.it
"""Tests for success_collapse.py (known-command output collapsing)."""
from __future__ import annotations

from synthelion.success_collapse import collapse, is_known_low_signal


class TestIsKnownLowSignal:
    def test_recognizes_npm_install(self):
        assert is_known_low_signal("npm install") is True

    def test_recognizes_npm_install_with_args(self):
        assert is_known_low_signal("npm install --save-dev jest") is True

    def test_recognizes_git_push(self):
        assert is_known_low_signal("git push origin main") is True

    def test_recognizes_docker_build(self):
        assert is_known_low_signal("docker build -t myimage .") is True

    def test_recognizes_terraform_apply(self):
        assert is_known_low_signal("terraform apply -auto-approve") is True

    def test_case_insensitive(self):
        assert is_known_low_signal("NPM INSTALL") is True

    def test_unknown_command_rejected(self):
        assert is_known_low_signal("python manage.py migrate") is False

    def test_empty_command_rejected(self):
        assert is_known_low_signal("") is False
        assert is_known_low_signal(None) is False

    def test_prefix_must_match_start(self):
        # "run npm install" should not match — "npm install" isn't at the start
        assert is_known_low_signal("run npm install") is False


class TestCollapse:
    def test_npm_install_added_packages_and_vulnerabilities(self):
        output = (
            "npm WARN deprecated foo@1.0.0\n"
            "added 42 packages in 3s\n"
            "2 vulnerabilities (1 moderate, 1 high)\n"
        )
        result = collapse(output, "npm install")
        assert result is not None
        assert "added 42 packages in 3s" in result
        assert "2 vulnerabilities" in result

    def test_docker_build_success_tag(self):
        output = (
            "Step 5/5 : CMD [\"node\", \"index.js\"]\n"
            " ---> Running in abc123\n"
            "Successfully built a1b2c3d4e5f6\n"
            "Successfully tagged myimage:latest\n"
        )
        result = collapse(output, "docker build -t myimage .")
        assert result is not None
        assert "Successfully built a1b2c3d4e5f6" in result
        assert "Successfully tagged myimage:latest" in result

    def test_git_push_ref_update(self):
        output = (
            "Enumerating objects: 5, done.\n"
            "Counting objects: 100% (5/5), done.\n"
            "   a1b2c3d..d4e5f6a  main -> main\n"
        )
        result = collapse(output, "git push origin main")
        assert result is not None
        assert "main -> main" in result

    def test_git_push_up_to_date(self):
        result = collapse("Everything up-to-date\n", "git push origin main")
        assert result is not None
        assert "Everything up-to-date" in result

    def test_terraform_apply_complete(self):
        output = (
            "aws_instance.web: Creating...\n"
            "aws_instance.web: Creation complete after 12s\n"
            "Apply complete! Resources: 1 added, 0 changed, 0 destroyed.\n"
        )
        result = collapse(output, "terraform apply -auto-approve")
        assert result is not None
        assert "Apply complete!" in result

    def test_returns_none_for_unrecognized_output(self):
        output = "some completely generic output\nwith nothing recognizable\n"
        result = collapse(output, "npm install")
        assert result is None

    def test_returns_none_for_unknown_command(self):
        output = "added 42 packages in 3s\n"
        result = collapse(output, "python manage.py migrate")
        assert result is None

    def test_returns_none_for_empty_content(self):
        assert collapse("", "npm install") is None

    def test_caps_at_three_facts(self):
        output = (
            "added 1 packages in 1s\n"
            "removed 2 packages in 1s\n"
            "changed 3 packages in 1s\n"
            "4 vulnerabilities found\n"
        )
        result = collapse(output, "npm install")
        assert result is not None
        assert len(result.splitlines()) <= 3

    def test_no_duplicate_facts(self):
        output = "added 1 packages in 1s\nadded 1 packages in 1s\n"
        result = collapse(output, "npm install")
        assert result is not None
        assert result.count("added 1 packages") == 1
