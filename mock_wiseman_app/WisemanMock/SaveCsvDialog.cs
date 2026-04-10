using System;
using System.Drawing;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// CSV保存ダイアログ（独自WinForms Form）。
    /// Windows共通のSaveFileDialogはpywinautoのApplication.window()から
    /// 検出できないため、テスト安定性のために独自Formで代替する。
    /// pywinauto セレクタ: title="名前を付けて保存"
    /// </summary>
    public class SaveCsvDialog : Form
    {
        private TextBox txtFileName;
        private Button btnSave;
        private Button btnCancel;

        public string FileName => txtFileName.Text;

        public SaveCsvDialog(string defaultFileName)
        {
            InitializeComponent(defaultFileName);
        }

        private void InitializeComponent(string defaultFileName)
        {
            this.Text = "Save CSV";
            this.Size = new Size(500, 160);
            this.StartPosition = FormStartPosition.CenterParent;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;

            var lblFileName = new Label
            {
                Text = "ファイル名:",
                Location = new Point(15, 22),
                AutoSize = true,
                Font = new Font("Meiryo UI", 9)
            };

            txtFileName = new TextBox
            {
                Name = "txtFileName",
                Text = defaultFileName,
                Location = new Point(95, 20),
                Size = new Size(370, 22)
            };

            btnSave = new Button
            {
                Name = "btnSave",
                Text = "保存(S)",
                Location = new Point(280, 65),
                Size = new Size(85, 30)
            };
            btnSave.Click += BtnSave_Click;

            btnCancel = new Button
            {
                Name = "btnCancel",
                Text = "キャンセル",
                Location = new Point(375, 65),
                Size = new Size(85, 30)
            };
            btnCancel.Click += BtnCancel_Click;

            this.Controls.AddRange(new Control[]
            {
                lblFileName, txtFileName, btnSave, btnCancel
            });
        }

        private void BtnSave_Click(object sender, EventArgs e)
        {
            this.DialogResult = DialogResult.OK;
            this.Close();
        }

        private void BtnCancel_Click(object sender, EventArgs e)
        {
            this.DialogResult = DialogResult.Cancel;
            this.Close();
        }
    }
}
