using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

[Collection("env-serial")]
public class LaunchValidationTests
{
    [Fact]
    public async Task InvalidOverrideFailsBeforeBinaryResolutionInEveryLaunchPath()
    {
        var original = Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH");
        var missingBinary = Path.Combine(Path.GetTempPath(), $"missing-cloak-{Guid.NewGuid()}");
        Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", missingBinary);
        try
        {
            await Assert.ThrowsAsync<ArgumentException>(() =>
                CloakLauncher.LaunchAsync(new LaunchOptions { GpuVendor = "   " }));
            await Assert.ThrowsAsync<ArgumentException>(() =>
                CloakLauncher.LaunchContextAsync(new LaunchContextOptions { GpuVendor = "   " }));
            await Assert.ThrowsAsync<ArgumentException>(() =>
                CloakLauncher.LaunchPersistentContextAsync(
                    Path.Combine(Path.GetTempPath(), $"profile-{Guid.NewGuid()}"),
                    new LaunchContextOptions { GpuVendor = "   " }));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", original);
        }
    }

    [Fact]
    public void ContextInnerOptionsPreserveLegacyPresetBehaviorWithoutOverrides()
    {
        var source = new LaunchContextOptions
        {
            FingerprintPreset = FingerprintPreset.Consistent,
            Headless = false,
            StealthArgs = false,
        };

        var mapped = CloakLauncher.BuildContextBrowserLaunchOptions(
            source, source.Args, source.Timezone, source.Locale);

        Assert.Equal(FingerprintPreset.Default, mapped.FingerprintPreset);
        Assert.False(mapped.Headless);
        Assert.False(mapped.StealthArgs);
    }

    [Fact]
    public void ContextInnerOptionsForwardAllSevenFingerprintOverrides()
    {
        var source = new LaunchContextOptions
        {
            GpuVendor = "Vendor",
            GpuRenderer = "Renderer",
            HardwareConcurrency = 12,
            DeviceMemory = 16,
            ScreenWidth = 2560,
            ScreenHeight = 1440,
            Brand = "BrowserCo",
        };

        var mapped = CloakLauncher.BuildContextBrowserLaunchOptions(
            source, source.Args, source.Timezone, source.Locale);

        Assert.Equal(source.GpuVendor, mapped.GpuVendor);
        Assert.Equal(source.GpuRenderer, mapped.GpuRenderer);
        Assert.Equal(source.HardwareConcurrency, mapped.HardwareConcurrency);
        Assert.Equal(source.DeviceMemory, mapped.DeviceMemory);
        Assert.Equal(source.ScreenWidth, mapped.ScreenWidth);
        Assert.Equal(source.ScreenHeight, mapped.ScreenHeight);
        Assert.Equal(source.Brand, mapped.Brand);
    }
}
