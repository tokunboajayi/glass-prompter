cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.5.2"
  sha256 arm:   "b1312ec306132d7161ba3dd01f9dc0752cec702ca4ce069e2718ff1e89cb6c28",
         intel: "7e810da48450ebea6413da8e68023836ff15f081a56788ed8a05e0f61a8ac6d2"

  url "https://github.com/tokunboajayi/glass-prompter/releases/download/v#{version}/GlassPrompter-#{version}-macOS-#{arch}.dmg"
  name "Glass Prompter"
  desc "See-through teleprompter under your webcam that follows your voice"
  homepage "https://tokunboajayi.github.io/glass-prompter/"

  livecheck do
    url :url
    strategy :github_latest
  end

  auto_updates true
  depends_on macos: ">= :ventura"

  app "Glass Prompter.app"

  zap trash: [
    "~/Library/Application Support/GlassPrompter",
    "~/Library/LaunchAgents/app.glassprompter.plist",
  ]

  caveats <<~EOS
    Glass Prompter is not notarized yet. The first time, right-click it in Applications and choose Open
    (on macOS 15+: System Settings > Privacy & Security > Open Anyway).
  EOS
end
