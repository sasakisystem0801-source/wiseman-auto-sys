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
            // 実機ワイズマンはUSBドングル認証後に「ワイズマンシステムSP」ランチャー(frmStartUp)
            // が開く。モックも同様にランチャーから起動する（ADR-007）。
            Application.Run(new LauncherForm());
        }
    }
}
