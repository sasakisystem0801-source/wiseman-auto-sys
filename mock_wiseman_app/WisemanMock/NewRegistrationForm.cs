using System;
using System.Drawing;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// 新規登録フォーム。実機の "frmKihon" に対応。
    /// pywinauto セレクタ: auto_id="frmKihon"
    ///
    /// 実機では MDI 子ウィンドウとして開かれ、親と同じタイトルを持つ。
    /// </summary>
    public class NewRegistrationForm : Form
    {
        public NewRegistrationForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Name = "frmKihon";
            this.Text = "基本情報登録 - 新規";
            this.Size = new Size(600, 400);
            this.StartPosition = FormStartPosition.CenterParent;

            var title = new Label
            {
                Text = "新規利用者登録",
                Font = new Font("Meiryo UI", 14, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(30, 20)
            };

            var lblName = new Label
            {
                Text = "氏名:",
                Location = new Point(30, 70),
                AutoSize = true
            };
            var txtName = new TextBox
            {
                Name = "txtUserName",
                Location = new Point(120, 67),
                Size = new Size(200, 22)
            };

            var btnCancel = new Button
            {
                Name = "btnCancel",
                Text = "キャンセル",
                Size = new Size(100, 35),
                Location = new Point(480, 320)
            };
            btnCancel.Click += (s, e) => this.Close();

            this.Controls.AddRange(new Control[] { title, lblName, txtName, btnCancel });
        }
    }
}
