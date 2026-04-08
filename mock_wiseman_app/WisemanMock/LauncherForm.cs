using System;
using System.Drawing;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// システム選択ランチャー。実機の "frmStartUp" に対応。
    /// pywinauto セレクタ: auto_id="frmStartUp"
    ///
    /// 実機ではケア記録システムの選択項目は Button ではなく Pane (Panel) として実装されている。
    /// このモックも Panel + Label の組み合わせで実装し、クリック時に MainForm を開く。
    /// </summary>
    public class LauncherForm : Form
    {
        private Button careSystemButton;

        public LauncherForm()
        {
            InitializeComponent();
        }

        private void InitializeComponent()
        {
            // Name プロパティが pywinauto の auto_id になる
            this.Name = "frmStartUp";
            this.Text = "ワイズマンシステムSP";
            this.Size = new Size(800, 500);
            this.StartPosition = FormStartPosition.CenterScreen;
            this.FormBorderStyle = FormBorderStyle.FixedSingle;
            this.MaximizeBox = false;

            var title = new Label
            {
                Text = "システム選択メニュー",
                Font = new Font("Meiryo UI", 14, FontStyle.Bold),
                AutoSize = true,
                Location = new Point(30, 20)
            };

            // ケア記録システム選択: 実機は Pane(Panel) だが、モックでは
            // Button を使用する。WinForms Button は Pane/Panel と異なり
            // WM_LBUTTONDOWN/UP の PostMessage にも BM_CLICK にも確実に反応するため、
            // pywinauto 経由の自動クリックが安定する。
            // pywinauto engine 側の探索は Pane → Text → Button の順で fallback するため、
            // Pane/Text が存在しないモック環境では Button にマッチする。
            // 実機テストでは実物の Pane に対して同じ PostMessage が送られる（別途検証）。
            careSystemButton = new Button
            {
                Name = "btnCareSystem",
                Text = "通所・訪問リハビリ管理システム SP(ケア記録)",
                Font = new Font("Meiryo UI", 11),
                Location = new Point(30, 70),
                Size = new Size(600, 60),
                BackColor = Color.LightBlue,
                FlatStyle = FlatStyle.Flat,
                UseVisualStyleBackColor = false,
            };
            careSystemButton.Click += CareSystemButton_Click;

            this.Controls.AddRange(new Control[] { title, careSystemButton });
        }

        private void CareSystemButton_Click(object sender, EventArgs e)
        {
            var mainForm = new MainForm();
            mainForm.Show();
            this.Hide();
            mainForm.FormClosed += (s, args) => this.Close();
        }
    }
}
