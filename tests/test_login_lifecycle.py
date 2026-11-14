import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock
from login_lifecycle import OwnedLogins
import cloud_uploader

class LoginLifecycleTests(TestCase):
    def test_exit_signals_only_owned_live_children_and_waits_for_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            alive=Mock();alive.poll.return_value=None
            done=Mock();done.poll.return_value=0
            launch=Mock(side_effect=[alive,done])
            children=OwnedLogins(directory,launch)
            children.start("ali");children.start("baidu")
            first=launch.call_args_list[0].kwargs["cancel_path"]
            second=launch.call_args_list[1].kwargs["cancel_path"]
            children.request_stop()
            self.assertTrue(first.is_file())
            self.assertFalse(second.exists())
            self.assertTrue(children.running())
            alive.poll.return_value=0
            self.assertFalse(children.running())
            self.assertFalse(first.exists())
            alive.terminate.assert_not_called()

    def test_owned_child_gets_unique_stop_marker_in_environment(self):
        from unittest.mock import patch
        with patch("cloud_uploader.subprocess.Popen") as spawn:
            cloud_uploader.launch_login("ali",Path("local-only.stop"))
            self.assertEqual(spawn.call_args.kwargs["env"]["DUALCLOUD_LOGIN_CANCEL"],"local-only.stop")

    def test_standalone_login_does_not_inherit_ownership(self):
        from unittest.mock import patch
        with patch.dict("os.environ",{"DUALCLOUD_LOGIN_CANCEL":"other.stop"}), patch("cloud_uploader.subprocess.Popen") as spawn:
            cloud_uploader.launch_login("baidu")
            self.assertNotIn("DUALCLOUD_LOGIN_CANCEL",spawn.call_args.kwargs["env"])
