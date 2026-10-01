param([string]$out)
Add-Type @"
using System; using System.Runtime.InteropServices;
public class GpDpi { [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }
"@
[GpDpi]::SetProcessDPIAware() | Out-Null
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object Drawing.Bitmap $b.Width, $b.Height
$g = [Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen(0, 0, 0, 0, $bmp.Size)
$bmp.Save($out)
