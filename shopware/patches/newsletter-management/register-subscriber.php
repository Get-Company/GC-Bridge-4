<?php declare(strict_types=1);
// Run from the Shopware root after uploading the subscriber class.
$file = getcwd() . '/custom/plugins/ClasseiShopTheme/src/Resources/config/services.xml';
$id = 'ClasseiShopTheme\\Subscriber\\NewsletterUnsubscribeSubscriber';
$xml = file_get_contents($file);
if (str_contains($xml, $id)) {
    echo "Newsletter unsubscribe subscriber already registered.\n";
    exit;
}
if (substr_count($xml, '</services>') !== 1) throw new RuntimeException('Unexpected services configuration.');
$block = '        <service id="' . $id . '">' . "\n"
    . '            <tag name="kernel.event_subscriber"/>' . "\n"
    . '        </service>' . "\n\n";
$updated = str_replace('    </services>', $block . '    </services>', $xml);
if (!simplexml_load_string($updated)) throw new RuntimeException('Invalid services configuration.');
$backup = getcwd() . '/var/gc-newsletter-setup/services-before-unsubscribe-confirmation.xml';
if (!file_exists($backup)) file_put_contents($backup, $xml);
file_put_contents($file . '.newsletter-new', $updated);
chmod($file . '.newsletter-new', fileperms($file) & 0777);
rename($file . '.newsletter-new', $file);
echo "Newsletter unsubscribe subscriber registered.\n";
