require 'rails_helper'

RSpec.describe AuditLogger do
  describe '.log' do
    let(:jwt_user_id) { SecureRandom.uuid }
    let(:explicit_user_id) { SecureRandom.uuid }
    let(:resource_id) { SecureRandom.uuid }

    let(:request) do
      instance_double(
        ActionDispatch::Request,
        env: { 'jwt.user_id' => jwt_user_id, 'jwt.user_email' => 'jwt@example.com' },
        remote_ip: '10.0.0.1',
        user_agent: 'RSpec'
      )
    end

    it 'records an audit log with actor and request metadata from the JWT env' do
      expect do
        described_class.log(action: 'quota.updated', resource_type: 'StorageQuota', resource_id: resource_id,
                            request: request, changes_made: { 'tier' => 'pro' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(
        action: 'quota.updated',
        resource_type: 'StorageQuota',
        resource_id: resource_id,
        actor_id: jwt_user_id,
        actor_email: 'jwt@example.com',
        ip_address: '10.0.0.1',
        user_agent: 'RSpec',
        changes_made: { 'tier' => 'pro' }
      )
    end

    it 'prefers explicitly passed actor details over the JWT env' do
      described_class.log(action: 'config.updated', resource_type: 'SystemConfig', request: request,
                          actor_id: explicit_user_id, actor_email: 'explicit@example.com')

      expect(AuditLog.last).to have_attributes(actor_id: explicit_user_id, actor_email: 'explicit@example.com')
    end

    it 'records without a request' do
      described_class.log(action: 'bulk.users_updated', resource_type: 'AdminUser')

      expect(AuditLog.last).to have_attributes(actor_id: nil, ip_address: nil, user_agent: nil)
    end

    it 'swallows and logs persistence failures instead of raising' do
      allow(Rails.logger).to receive(:error)

      expect do
        described_class.log(action: nil, resource_type: 'AdminUser')
      end.not_to raise_error

      expect(AuditLog.count).to eq(0)
      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
