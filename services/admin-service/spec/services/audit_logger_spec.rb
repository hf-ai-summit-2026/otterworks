require 'rails_helper'

RSpec.describe AuditLogger do
  describe '.log' do
    let(:jwt_user_id) { SecureRandom.uuid }
    let(:resource_id) { SecureRandom.uuid }
    let(:request) do
      instance_double(
        ActionDispatch::Request,
        env: { 'jwt.user_id' => jwt_user_id, 'jwt.user_email' => 'jwt@example.com' },
        remote_ip: '10.0.0.1',
        user_agent: 'RSpec'
      )
    end

    it 'records an audit log with actor and client details taken from the request' do
      expect do
        described_class.log(action: 'config.updated', resource_type: 'SystemConfig', resource_id: resource_id,
                            request: request, changes_made: { 'key' => 'value' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'config.updated',
        resource_type: 'SystemConfig',
        resource_id: resource_id,
        actor_id: jwt_user_id,
        actor_email: 'jwt@example.com',
        changes_made: { 'key' => 'value' },
        ip_address: '10.0.0.1',
        user_agent: 'RSpec'
      )
    end

    it 'prefers explicitly passed actor details over the request JWT' do
      explicit_id = SecureRandom.uuid
      described_class.log(action: 'user.updated', resource_type: 'AdminUser', request: request,
                          actor_id: explicit_id, actor_email: 'explicit@example.com')

      expect(AuditLog.last).to have_attributes(actor_id: explicit_id, actor_email: 'explicit@example.com')
    end

    it 'records a log without a request' do
      described_class.log(action: 'bulk.users_updated', resource_type: 'AdminUser')

      expect(AuditLog.last).to have_attributes(actor_id: nil, actor_email: nil, ip_address: nil, user_agent: nil)
    end

    it 'swallows and logs errors instead of raising' do
      allow(AuditLog).to receive(:record!).and_raise(StandardError, 'db down')
      allow(Rails.logger).to receive(:error)

      expect { described_class.log(action: 'user.updated', resource_type: 'AdminUser') }.not_to raise_error
      expect(Rails.logger).to have_received(:error).with('Failed to record audit log: db down')
    end
  end
end
