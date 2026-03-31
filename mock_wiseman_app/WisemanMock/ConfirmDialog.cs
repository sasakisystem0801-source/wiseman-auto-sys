using System;
using System.Drawing;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// 終了確認ダイアログ。pywinauto セレクタ: title_re=".*確認.*"
    /// </summary>
    public class ConfirmDialog : Form
    {
        private Label lblMessage;
        private Button btnYes;
        private Button btnNo;

        public ConfirmDialog(string message)
        {
            InitializeComponent(message);
        }

        private void InitializeComponent(string message)
        {
            this.Text = "確認";
            this.Size = new Size(300, 150);
            this.StartPosition = FormStartPosition.CenterParent;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;

            lblMessage = new Label
            {
                Name = "lblMessage",
                Text = message,
                Location = new Point(30, 20),
                AutoSize = true,
                Font = new Font("Meiryo UI", 10)
            };

            btnYes = new Button
            {
                Name = "btnYes",
                Text = "はい",
                Location = new Point(50, 65),
                Size = new Size(80, 30),
                DialogResult = DialogResult.Yes
            };

            btnNo = new Button
            {
                Name = "btnNo",
                Text = "いいえ",
                Location = new Point(150, 65),
                Size = new Size(80, 30),
                DialogResult = DialogResult.No
            };

            this.AcceptButton = btnYes;
            this.CancelButton = btnNo;

            this.Controls.AddRange(new Control[] { lblMessage, btnYes, btnNo });
        }
    }
}
