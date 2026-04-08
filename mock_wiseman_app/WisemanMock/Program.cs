using System;
using System.Windows.Forms;

namespace WisemanMock
{
    static class Program
    {
        [STAThread]
        static void Main()
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            // 実機ワイズマンはUSBドングル認証のみでログイン画面がないため、
            // モックも起動直後に MainForm を直接表示する（ADR-007参照）
            Application.Run(new MainForm());
        }
    }
}
