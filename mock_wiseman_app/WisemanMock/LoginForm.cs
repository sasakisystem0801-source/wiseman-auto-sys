using System;
using System.Drawing;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// ログイン画面。pywinauto セレクタ: title_re=".*ログイン.*"
    /// </summary>
    public class LoginForm : Form
    {
        private TextBox txtUserId;
        private TextBox txtPassword;
        private Button btnLogin;
        private Label lblUserId;
        private Label lblPassword;
        private Label lblTitle;

        public LoginForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Text = "ログイン";
            this.Size = new Size(350, 250);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;

            lblTitle = new Label
            {
                Text = "ワイズマンシステム SP",
                Font = new Font("Meiryo UI", 14, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(60, 15)
            };

            lblUserId = new Label
            {
                Text = "ユーザーID:",
                Location = new Point(30, 65),
                AutoSize = true
            };

            txtUserId = new TextBox
            {
                Name = "txtUserId",          // AutomationId = "txtUserId"
                Location = new Point(130, 62),
                Size = new Size(170, 22)
            };

            lblPassword = new Label
            {
                Text = "パスワード:",
                Location = new Point(30, 100),
                AutoSize = true
            };

            txtPassword = new TextBox
            {
                Name = "txtPassword",        // AutomationId = "txtPassword"
                Location = new Point(130, 97),
                Size = new Size(170, 22),
                PasswordChar = '*'
            };

            btnLogin = new Button
            {
                Name = "btnLogin",           // AutomationId = "btnLogin"
                Text = "ログイン",
                Location = new Point(130, 140),
                Size = new Size(100, 35)
            };
            btnLogin.Click += BtnLogin_Click;

            this.AcceptButton = btnLogin;

            this.Controls.AddRange(new Control[]
            {
                lblTitle, lblUserId, txtUserId, lblPassword, txtPassword, btnLogin
            });
        }

        private void BtnLogin_Click(object sender, EventArgs e)
        {
            if (string.IsNullOrWhiteSpace(txtUserId.Text) ||
                string.IsNullOrWhiteSpace(txtPassword.Text))
            {
                MessageBox.Show("ユーザーIDとパスワードを入力してください。",
                    "入力エラー", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }

            var mainForm = new MainForm();
            mainForm.Show();
            this.Hide();
        }
    }
}
