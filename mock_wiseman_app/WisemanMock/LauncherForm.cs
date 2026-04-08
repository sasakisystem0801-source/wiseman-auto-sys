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
        private Panel careSystemPanel;
        private Label careSystemLabel;

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

            // ケア記録システム選択 Pane (WinForms Panel → UIA Pane)
            // UIA では Control.Name プロパティは AutomationId に、AccessibleName は UIA Name(title) に
            // マッピングされる。pywinauto の title_re は UIA Name にマッチするため、
            // AccessibleName を設定する必要がある（実機側の Pane も同じ方式で title を公開している）。
            // 実機は半角カナ "ｹｱ記録" だがモックは全角で OK（engine 側の正規表現でマッチする）。
            careSystemPanel = new Panel
            {
                Name = "pnlCareSystem",
                AccessibleName = "通所・訪問リハビリ管理システム SP(ケア記録)",
                Location = new Point(30, 70),
                Size = new Size(600, 60),
                BorderStyle = BorderStyle.FixedSingle,
                BackColor = Color.LightBlue,
                Cursor = Cursors.Hand
            };

            careSystemLabel = new Label
            {
                Text = "通所・訪問リハビリ管理システム SP(ケア記録)",
                Font = new Font("Meiryo UI", 11),
                AutoSize = false,
                TextAlign = ContentAlignment.MiddleCenter,
                Dock = DockStyle.Fill,
            };
            careSystemPanel.Controls.Add(careSystemLabel);

            // Panel 自体と Label の両方にクリックイベントを付与
            careSystemPanel.Click += CareSystemPanel_Click;
            careSystemLabel.Click += CareSystemPanel_Click;

            this.Controls.AddRange(new Control[] { title, careSystemPanel });
        }

        private void CareSystemPanel_Click(object sender, EventArgs e)
        {
            var mainForm = new MainForm();
            mainForm.Show();
            this.Hide();
            mainForm.FormClosed += (s, args) => this.Close();
        }
    }
}
