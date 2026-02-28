'use strict';
'require view';
'require form';

return view.extend({
	render: function () {
		var m, s, o;

		m = new form.Map('salt-openwrt', _('Salt Agent'),
			_('Configure how Salt manages this device. ' +
			  'The Salt state module reads this configuration at the start ' +
			  'of every run to determine its behavior.'));

		s = m.section(form.NamedSection, 'global', 'salt-openwrt',
			_('Agent Settings'));

		o = s.option(form.Flag, 'enabled', _('Enable Salt management'),
			_('When disabled, Salt skips this device entirely. ' +
			  'No configuration is read, no changes are made.'));
		o.rmempty = false;
		o.default = '1';

		o = s.option(form.ListValue, 'mode', _('Operating mode'),
			_('Controls what Salt is allowed to do on this device.'));
		o.value('audit', _('Audit') + ' -- ' +
			_('Read-only. Salt reports configuration drift but makes no changes.'));
		o.value('manual', _('Manual') + ' -- ' +
			_('Salt stages changes but does not apply them. ' +
			  'An operator reviews and activates.'));
		o.value('auto', _('Auto') + ' -- ' +
			_('Full automation. Salt applies changes with rollback protection.'));
		o.default = 'audit';

		o = s.option(form.Flag, 'require_commit', _('Require explicit commit'),
			_('Reserved for future use.'));
		o.rmempty = false;
		o.default = '0';

		o = s.option(form.DummyValue, 'last_run', _('Last state run'));
		o.placeholder = _('No data');

		o = s.option(form.DummyValue, 'last_drift', _('Last drift detected'));
		o.placeholder = _('No data');

		return m.render();
	}
});
