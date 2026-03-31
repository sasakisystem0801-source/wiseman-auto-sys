using System;
using System.Drawing;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// MDI親ウィンドウ。pywinauto セレクタ: title_re=".*管理システム SP.*"
    /// </summary>
    public class MainForm : Form
    {
        private MenuStrip mainMenu;
        private Button btnExit;
        private StatusStrip statusBar;
        private ToolStripStatusLabel statusLabel;

        public MainForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            this.Text = "通所・訪問リハビリ管理システム SP(ケア記録) [テスト施設]";
            this.Size = new Size(1024, 768);
            this.IsMdiContainer = true;
            this.StartPosition = FormStartPosition.CenterScreen;

            // MenuStrip
            mainMenu = new MenuStrip { Name = "mainMenu" };

            var menuCareRecord = new ToolStripMenuItem("ケア記録");
            var menuSummary = new ToolStripMenuItem("集計表");
            menuSummary.Click += MenuSummary_Click;
            menuCareRecord.DropDownItems.Add(menuSummary);

            var menuMaster = new ToolStripMenuItem("マスタ");
            var menuUser = new ToolStripMenuItem("利用者管理");
            menuMaster.DropDownItems.Add(menuUser);

            mainMenu.Items.AddRange(new ToolStripItem[] { menuCareRecord, menuMaster });

            // Exit button
            btnExit = new Button
            {
                Name = "btnExit",
                Text = "終了",
                Size = new Size(80, 35),
                Anchor = AnchorStyles.Bottom | AnchorStyles.Right
            };
            btnExit.Click += BtnExit_Click;

            // StatusStrip
            statusBar = new StatusStrip { Name = "statusBar" };
            statusLabel = new ToolStripStatusLabel("ログイン中");
            statusBar.Items.Add(statusLabel);

            this.MainMenuStrip = mainMenu;
            this.Controls.Add(mainMenu);
            this.Controls.Add(statusBar);
            this.Controls.Add(btnExit);

            // Position exit button
            this.Load += (s, e) =>
            {
                btnExit.Location = new Point(
                    this.ClientSize.Width - btnExit.Width - 20,
                    this.ClientSize.Height - btnExit.Height - statusBar.Height - 10);
            };
            this.Resize += (s, e) =>
            {
                btnExit.Location = new Point(
                    this.ClientSize.Width - btnExit.Width - 20,
                    this.ClientSize.Height - btnExit.Height - statusBar.Height - 10);
            };

            this.FormClosing += MainForm_FormClosing;
        }

        private void MenuSummary_Click(object sender, EventArgs e)
        {
            var careForm = new CareRecordForm { MdiParent = this };
            careForm.Show();
            statusLabel.Text = "ケア記録集計表を表示中";
        }

        private void BtnExit_Click(object sender, EventArgs e)
        {
            ShowExitConfirm();
        }

        private void MainForm_FormClosing(object sender, FormClosingEventArgs e)
        {
            if (e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                ShowExitConfirm();
            }
        }

        private void ShowExitConfirm()
        {
            using (var dlg = new ConfirmDialog("終了しますか？"))
            {
                if (dlg.ShowDialog(this) == DialogResult.Yes)
                {
                    this.FormClosing -= MainForm_FormClosing;
                    Application.Exit();
                }
            }
        }
    }
}
