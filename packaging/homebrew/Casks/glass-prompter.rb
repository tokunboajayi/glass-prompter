cask "glass-prompter" do
  arch arm: "arm64", intel: "x86_64"

  version "2.6.1"
  sha256 arm:   "c35df3f8c8a0da13370c49ca827c7703451d5c337f5806c7c562233abcc3b4b1",
         intel: "e126c98cd2b5ed8618468e3f6f86d1a3eceee353779b303426177248430604bb"

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
