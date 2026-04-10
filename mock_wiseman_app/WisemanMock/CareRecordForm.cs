using System;
using System.Drawing;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace WisemanMock
{
    /// <summary>
    /// ケア記録集計表（MDI子ウィンドウ）。pywinauto セレクタ: title="ケア記録集計表"
    /// </summary>
    public class CareRecordForm : Form
    {
        private DataGridView dgvCareRecord;
        private Button btnPrint;
        private Button btnClose;
        private Button btnHelp;
        private ComboBox cmbLayout;
        private ComboBox cmbMonth;
        private CheckBox chkTusho;
        private CheckBox chkYoboTusho;
        private CheckBox chkHomon;
        private CheckBox chkYoboHomon;
        private Label lblFilter;

        public CareRecordForm()
        {
            InitializeComponent();
            LoadMockData();
        }

        private void InitializeComponent()
        {
            this.Text = "ケア記録集計表";
            this.Size = new Size(950, 600);

            // Top button panel
            var topPanel = new Panel
            {
                Dock = DockStyle.Top,
                Height = 40
            };

            btnHelp = new Button
            {
                Name = "btnHelp",
                Text = "ヘルプ",
                Location = new Point(5, 7),
                Size = new Size(70, 28)
            };

            btnPrint = new Button
            {
                Name = "btnPrint",
                Text = "印 刷",
                Location = new Point(80, 7),
                Size = new Size(70, 28)
            };
            btnPrint.Click += BtnPrint_Click;

            btnClose = new Button
            {
                Name = "btnClose",
                Text = "閉じる",
                Location = new Point(155, 7),
                Size = new Size(70, 28)
            };
            btnClose.Click += BtnClose_Click;

            topPanel.Controls.AddRange(new Control[] { btnHelp, btnPrint, btnClose });

            // Filter panel
            var filterPanel = new Panel
            {
                Dock = DockStyle.Top,
                Height = 40
            };

            var lblLayout = new Label
            {
                Text = "レイアウト:",
                Location = new Point(5, 10),
                AutoSize = true
            };

            cmbLayout = new ComboBox
            {
                Name = "cmbLayout",
                Location = new Point(80, 7),
                Size = new Size(180, 22),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            cmbLayout.Items.AddRange(new object[]
            {
                "01 [バイタル記録表]",
                "02 [服薬記録表]",
                "03 [リハビリ記録表]"
            });
            cmbLayout.SelectedIndex = 0;

            cmbMonth = new ComboBox
            {
                Name = "cmbMonth",
                Location = new Point(280, 7),
                Size = new Size(140, 22),
                DropDownStyle = ComboBoxStyle.DropDownList
            };
            cmbMonth.Items.AddRange(new object[]
            {
                "令和08年03月",
                "令和08年02月",
                "令和08年01月"
            });
            cmbMonth.SelectedIndex = 0;

            filterPanel.Controls.AddRange(new Control[] { lblLayout, cmbLayout, cmbMonth });

            // Checkbox panel
            var checkPanel = new Panel
            {
                Dock = DockStyle.Top,
                Height = 35
            };

            chkTusho = new CheckBox
            {
                Name = "chkTusho",
                Text = "通所リハ",
                Location = new Point(5, 7),
                AutoSize = true,
                Checked = true
            };

            chkYoboTusho = new CheckBox
            {
                Name = "chkYoboTusho",
                Text = "予防通所リハ",
                Location = new Point(110, 7),
                AutoSize = true,
                Checked = true
            };

            chkHomon = new CheckBox
            {
                Name = "chkHomon",
                Text = "訪問リハ",
                Location = new Point(240, 7),
                AutoSize = true,
                Checked = true
            };

            chkYoboHomon = new CheckBox
            {
                Name = "chkYoboHomon",
                Text = "予防訪問リハ",
                Location = new Point(340, 7),
                AutoSize = true,
                Checked = true
            };

            lblFilter = new Label
            {
                Text = "絞込 5 人/総人数 5 人",
                Location = new Point(500, 10),
                AutoSize = true
            };

            checkPanel.Controls.AddRange(new Control[]
            {
                chkTusho, chkYoboTusho, chkHomon, chkYoboHomon, lblFilter
            });

            // DataGridView
            dgvCareRecord = new DataGridView
            {
                Name = "dgvCareRecord",
                Dock = DockStyle.Fill,
                ReadOnly = true,
                AllowUserToAddRows = false,
                AllowUserToDeleteRows = false,
                AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.AllCells,
                SelectionMode = DataGridViewSelectionMode.FullRowSelect
            };

            // Order matters: last added with Dock.Top goes on top
            this.Controls.Add(dgvCareRecord);
            this.Controls.Add(checkPanel);
            this.Controls.Add(filterPanel);
            this.Controls.Add(topPanel);
        }

        private void LoadMockData()
        {
            var data = MockData.GetCareRecordData();

            // Add columns
            dgvCareRecord.Columns.Add("colName", "利用者名");
            dgvCareRecord.Columns.Add("colItem", "ケア記録項目");
            for (int d = 1; d <= 31; d++)
            {
                dgvCareRecord.Columns.Add($"colDay{d}", d.ToString());
            }
            dgvCareRecord.Columns.Add("colCount", "件数");
            dgvCareRecord.Columns.Add("colAvg", "平均");
            dgvCareRecord.Columns.Add("colMax", "最大");
            dgvCareRecord.Columns.Add("colMin", "最小");

            // Add rows
            foreach (var row in data)
            {
                dgvCareRecord.Rows.Add(row);
            }
        }

        private void BtnPrint_Click(object sender, EventArgs e)
        {
            // SaveFileDialog（Windows共通ダイアログ）はpywinautoの
            // Application.window()から検出できないため、独自Formを使用する。
            // modeless (Show) にすることで click_input() がブロックしない。
            var dlg = new SaveCsvDialog("ケア記録集計表.csv");
            dlg.FormClosed += (s, args) =>
            {
                if (dlg.DialogResult == DialogResult.OK)
                {
                    ExportToCsv(dlg.FileName);
                }
                dlg.Dispose();
            };
            dlg.Show(this);
        }

        private void ExportToCsv(string filePath)
        {
            var sb = new StringBuilder();
            var encoding = Encoding.GetEncoding("shift_jis");

            // Header
            for (int c = 0; c < dgvCareRecord.Columns.Count; c++)
            {
                if (c > 0) sb.Append(",");
                sb.Append(dgvCareRecord.Columns[c].HeaderText);
            }
            sb.AppendLine();

            // Data
            for (int r = 0; r < dgvCareRecord.Rows.Count; r++)
            {
                for (int c = 0; c < dgvCareRecord.Columns.Count; c++)
                {
                    if (c > 0) sb.Append(",");
                    var val = dgvCareRecord.Rows[r].Cells[c].Value;
                    sb.Append(val != null ? val.ToString() : "");
                }
                sb.AppendLine();
            }

            File.WriteAllText(filePath, sb.ToString(), encoding);
        }

        private void BtnClose_Click(object sender, EventArgs e)
        {
            this.Close();
        }
    }
}
