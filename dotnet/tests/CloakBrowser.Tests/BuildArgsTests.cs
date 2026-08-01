using CloakBrowser;
using System.Text.Json;
using Xunit;

namespace CloakBrowser.Tests;

public class BuildArgsTests
{
    private sealed class FingerprintOverrideFixture
    {
        public List<string> RawArgs { get; set; } = [];
        public Dictionary<string, JsonElement> OverrideInput { get; set; } = [];
        public List<string> ExpectedOverrideFlags { get; set; } = [];
    }

    private static FingerprintOverrideFixture ReadFingerprintOverrideFixture()
    {
        var root = FindRepositoryRoot();
        var path = Path.Combine(root, "tests", "fixtures", "fingerprint_override_parity.json");
        return JsonSerializer.Deserialize<FingerprintOverrideFixture>(File.ReadAllText(path),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory != null && !File.Exists(Path.Combine(directory.FullName, ".git")))
            directory = directory.Parent;
        return directory?.FullName ?? throw new DirectoryNotFoundException("Repository root not found");
    }

    [Fact]
    public void FingerprintOverride_ValuesReplaceRawDuplicatesAfterSeed()
    {
        var fixture = ReadFingerprintOverrideFixture();
        var input = fixture.OverrideInput;

        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: fixture.RawArgs,
            headless: true,
            gpuVendor: input["gpu_vendor"].GetString(),
            gpuRenderer: input["gpu_renderer"].GetString(),
            hardwareConcurrency: input["hardware_concurrency"].GetInt32(),
            deviceMemory: input["device_memory"].GetInt32(),
            screenWidth: input["screen_width"].GetInt32(),
            screenHeight: input["screen_height"].GetInt32(),
            brand: input["brand"].GetString());

        Assert.Equal(fixture.ExpectedOverrideFlags, args.TakeLast(7));
        Assert.True(args.IndexOf("--fingerprint=424242") < args.IndexOf(fixture.ExpectedOverrideFlags[0]));
        Assert.Single(args, arg => arg == fixture.ExpectedOverrideFlags[0]);
        Assert.DoesNotContain("--fingerprint-gpu-vendor=old", args);
    }

    [Fact]
    public void FingerprintOverride_OmittedValuesPreserveBaseline()
    {
        var fixture = ReadFingerprintOverrideFixture();
        var baseline = CloakLauncher.BuildArgs(false, fixture.RawArgs, headless: true);

        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: fixture.RawArgs,
            headless: true,
            gpuVendor: null,
            gpuRenderer: null,
            hardwareConcurrency: null,
            deviceMemory: null,
            screenWidth: null,
            screenHeight: null,
            brand: null);

        Assert.Equal(baseline, args);
    }

    [Theory]
    [InlineData("gpuVendor", "")]
    [InlineData("gpuRenderer", "   ")]
    [InlineData("brand", " ")]
    public void FingerprintOverride_RejectsEmptyStrings(string field, string value)
    {
        var exception = Assert.Throws<ArgumentException>(() => field switch
        {
            "gpuVendor" => CloakLauncher.BuildArgs(false, [], gpuVendor: value),
            "gpuRenderer" => CloakLauncher.BuildArgs(false, [], gpuRenderer: value),
            "brand" => CloakLauncher.BuildArgs(false, [], brand: value),
            _ => throw new InvalidOperationException(),
        });

        Assert.Contains(field, exception.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("hardwareConcurrency", 0)]
    [InlineData("deviceMemory", 1025)]
    [InlineData("screenWidth", 319)]
    [InlineData("screenHeight", 16385)]
    public void FingerprintOverride_RejectsOutOfRangeIntegers(string field, int value)
    {
        var exception = Assert.Throws<ArgumentOutOfRangeException>(() => field switch
        {
            "hardwareConcurrency" => CloakLauncher.BuildArgs(false, [], hardwareConcurrency: value),
            "deviceMemory" => CloakLauncher.BuildArgs(false, [], deviceMemory: value),
            "screenWidth" => CloakLauncher.BuildArgs(false, [], screenWidth: value),
            "screenHeight" => CloakLauncher.BuildArgs(false, [], screenHeight: value),
            _ => throw new InvalidOperationException(),
        });

        Assert.Contains(field, exception.Message, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void FingerprintOverride_ScreenValuesDoNotAddViewportFlags()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: [],
            screenWidth: 1920,
            screenHeight: 1080);

        Assert.Contains("--fingerprint-screen-width=1920", args);
        Assert.Contains("--fingerprint-screen-height=1080", args);
        Assert.DoesNotContain(args, arg => arg.StartsWith("--window-size") || arg.Contains("viewport"));
    }

    [Fact]
    public void ConsistentPresetAddsNoiseFlagAndPersistentQuota()
    {
        var args = CloakLauncher.BuildArgs(false, null,
            fingerprintPreset: FingerprintPreset.Consistent, persistent: true);
        Assert.Contains("--fingerprint-noise=false", args);
        Assert.Contains("--fingerprint-storage-quota=10240", args);
    }

    [Fact]
    public void CallerArgsOverrideConsistentPreset()
    {
        var args = CloakLauncher.BuildArgs(false,
            new List<string> { "--fingerprint-noise=true" },
            fingerprintPreset: FingerprintPreset.Consistent);
        Assert.Contains("--fingerprint-noise=true", args);
        Assert.DoesNotContain("--fingerprint-noise=false", args);
    }
    [Fact]
    public void Dedupes_By_FlagKey_UserOverridesStealth()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: true,
            extraArgs: new List<string> { "--no-sandbox=foo" },
            headless: true);
        // --no-sandbox should appear once, with the user's value winning.
        Assert.Single(args, a => a.StartsWith("--no-sandbox"));
        Assert.Contains("--no-sandbox=foo", args);
    }

    [Fact]
    public void Timezone_And_Locale_Flags_Injected()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: null,
            timezone: "America/New_York",
            locale: "en-US",
            headless: true);
        Assert.Contains("--fingerprint-timezone=America/New_York", args);
        Assert.Contains("--lang=en-US", args);
        Assert.Contains("--fingerprint-locale=en-US", args);
    }

    [Fact]
    public void Headed_Adds_IgnoreGpuBlocklist()
    {
        var args = CloakLauncher.BuildArgs(stealthArgs: false, extraArgs: null, headless: false);
        Assert.Contains("--ignore-gpu-blocklist", args);
    }

    [Fact]
    public void DedicatedParams_Override_UserArgs()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: new List<string> { "--fingerprint-timezone=Europe/London" },
            timezone: "Asia/Tokyo",
            headless: true);
        Assert.Single(args, a => a.StartsWith("--fingerprint-timezone"));
        Assert.Contains("--fingerprint-timezone=Asia/Tokyo", args);
    }

    [Fact]
    public void ExtensionPaths_Produce_LoadExtension_And_DisableExcept()
    {
        var tmp = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var args = CloakLauncher.BuildArgs(
                stealthArgs: false,
                extraArgs: null,
                extensionPaths: new List<string> { tmp });
            Assert.Contains(args, a => a.StartsWith("--load-extension="));
            Assert.Contains(args, a => a.StartsWith("--disable-extensions-except="));
        }
        finally { Directory.Delete(tmp); }
    }

    [Fact]
    public void NoLocale_NoTimezone_NoFlags()
    {
        var args = CloakLauncher.BuildArgs(stealthArgs: false, extraArgs: null, headless: true);
        Assert.DoesNotContain(args, a => a.StartsWith("--lang="));
        Assert.DoesNotContain(args, a => a.StartsWith("--fingerprint-timezone="));
    }

    [Fact]
    public void StartMaximized_True_AddsFlag()
    {
        var args = CloakLauncher.BuildArgs(stealthArgs: true, extraArgs: null, startMaximized: true);
        Assert.Contains("--start-maximized", args);
    }

    [Fact]
    public void StartMaximized_DefaultOff_NoFlag()
    {
        var args = CloakLauncher.BuildArgs(stealthArgs: true, extraArgs: null);
        Assert.DoesNotContain("--start-maximized", args);
    }

    [Fact]
    public void StartMaximized_SuppressedByUserWindowSize()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: true,
            extraArgs: new List<string> { "--window-size=1000,800" },
            startMaximized: true);
        Assert.DoesNotContain("--start-maximized", args);
        Assert.Contains("--window-size=1000,800", args);
    }

    [Fact]
    public void StartMaximized_NotDoubled()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: true,
            extraArgs: new List<string> { "--start-maximized" },
            startMaximized: true);
        Assert.Single(args, a => a == "--start-maximized");
    }
}
