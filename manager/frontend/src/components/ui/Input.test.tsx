import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Input } from './Input';

describe('Input password toggle', () => {
  it('renders a show/hide toggle for password inputs and flips visibility on click', async () => {
    const user = userEvent.setup();
    render(<Input type="password" aria-label="Password" />);

    const input = screen.getByLabelText('Password') as HTMLInputElement;
    expect(input).toHaveAttribute('type', 'password');

    const showButton = screen.getByRole('button', { name: /show password/i });
    expect(showButton).toHaveAttribute('type', 'button');

    await user.click(showButton);
    expect(input).toHaveAttribute('type', 'text');
    expect(screen.getByRole('button', { name: /hide password/i })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /hide password/i }));
    expect(input).toHaveAttribute('type', 'password');
    expect(screen.getByRole('button', { name: /show password/i })).toBeInTheDocument();
  });

  it('does not render a toggle button for non-password inputs', () => {
    render(<Input type="text" aria-label="Name" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('does not render a toggle button when no type is specified', () => {
    render(<Input aria-label="Name" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
