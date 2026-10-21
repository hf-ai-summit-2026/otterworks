require 'rails_helper'

RSpec.describe JwtAuthenticator do
  subject(:middleware) { described_class.new(app) }

  let(:app) { ->(env) { [200, {}, [env['jwt.user_id'].to_s]] } }
  let(:user_id) { SecureRandom.uuid }

  def call(path, headers = {})
    middleware.call(Rack::MockRequest.env_for(path, headers))
  end

  def bearer(token)
    { 'HTTP_AUTHORIZATION' => "Bearer #{token}" }
  end

  it 'skips authentication for excluded paths' do
    status, = call('/health')
    expect(status).to eq(200)
  end

  it 'rejects requests without a token' do
    status, _headers, body = call('/api/v1/admin/users')
    expect(status).to eq(401)
    expect(JSON.parse(body.first)).to eq('error' => 'Missing authorization token')
  end

  it 'rejects a non-Bearer authorization header' do
    status, = call('/api/v1/admin/users', 'HTTP_AUTHORIZATION' => 'Basic abc')
    expect(status).to eq(401)
  end

  it 'rejects a token signed with the wrong secret' do
    token = JWT.encode({ sub: user_id, exp: 1.hour.from_now.to_i }, 'wrong-secret', 'HS256')
    status, _headers, body = call('/api/v1/admin/users', bearer(token))
    expect(status).to eq(401)
    expect(JSON.parse(body.first)).to eq('error' => 'Invalid or expired token')
  end

  it 'rejects an expired token' do
    token = JWT.encode({ sub: user_id, exp: 1.minute.ago.to_i }, Rails.application.config.x.jwt_secret, 'HS256')
    status, = call('/api/v1/admin/users', bearer(token))
    expect(status).to eq(401)
  end

  it 'accepts a token signed with the configured secret and exposes its claims' do
    status, _headers, body = call('/api/v1/admin/users', bearer(jwt_token(user_id: user_id)))
    expect(status).to eq(200)
    expect(body.first).to eq(user_id)
  end

  it 'prefers JWT_SECRET from the environment over config/jwt.yml' do
    token = JWT.encode({ sub: user_id, exp: 1.hour.from_now.to_i }, 'env-secret', 'HS256')
    with_env('JWT_SECRET' => 'env-secret') do
      status, = call('/api/v1/admin/users', bearer(token))
      expect(status).to eq(200)
    end
  end

  it 'loads the test secret from config/jwt.yml' do
    expect(Rails.application.config.x.jwt_secret).to eq('test_jwt_secret_key')
  end
end
